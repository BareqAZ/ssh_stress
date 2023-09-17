#!/usr/bin/env python3
import asyncio, asyncssh, time, os, threading, sys, argparse, json
from typing import Optional
from itertools import cycle
import matplotlib.pyplot as plt

def gen_graph(data:dict):
    global_wait     = data["global_wait"]
    conn_wait       = data["conn_wait"]
    conns_per_sec   = data["conns_per_sec"]
    perf_times      = data["round_data"]

    cols = len(perf_times)

    _, ax = plt.subplots(1, cols, figsize=(10, 1*5))
    axs = [ax] if cols == 1 else ax

    if global_wait > 0:
        target_wait_time = global_wait
    else:
        target_wait_time = conn_wait

    round_index = 0
    for round_name, stress_round in perf_times.items():
        if len(stress_round["conn_data"]) < 2:
            print("ERROR: Could not generate the graph, not enough data")
            return

        x_axis   = []
        y1_axis  = []
        y2_axis  = []
        failed   = []
        max_time = 0

        for data in stress_round["conn_data"].values():
            x_axis.append(data["id"])
            if data["success"]:
                y1_axis.append(data["conn_time"])
                y2_axis.append(data["auth_time"])
                max_time = max(max_time, data["conn_time"])
            else:
                y1_axis.append(None)
                y2_axis.append(None)
                failed.append(data["id"])

        axs[round_index].plot(x_axis, y1_axis, label='conn time')
        axs[round_index].plot(x_axis, y2_axis, label='auth time')

        for f in failed:
            axs[round_index].plot(f, 2, marker='x', color='r')

        axs[round_index].axhline(y=target_wait_time, color="r", linestyle="--", label="Target conn time")
        axs[round_index].plot([], [], label=f'speed: {conns_per_sec}/cps')
        axs[round_index].plot([], [], label=f'failed: {len(failed)}')
        axs[round_index].legend([
                    f"connection duration ({round(stress_round['avg_conn_time'], 2)}s)",
                    f"authentication duration ({round(stress_round['avg_auth_time'], 2)}s)",
                    f"Target time: {target_wait_time}s",
                    f"speed: {conns_per_sec}/cps",
                    f"failed: {len(failed)}"
                    ])

        axs[round_index].set_ylim(0, max_time * 1.25)
        axs[round_index].set_xlabel("Connection")
        axs[round_index].set_ylabel("Time (seconds)")
        axs[round_index].set_title(f"Graph for {round_name}")
        round_index += 1

    plt.tight_layout()
    plt.show()


def drop_all_timer(n):
    global wait
    if n == 0:
        wait=False
        return
    print(f'Dropping all connections in {n} seconds')
    wait=True
    time.sleep(n)
    print(f'Dropping all connections now')
    wait=False

class SSHstress:
    def __init__(
        self, 
        target_address:str,
        target_users:list           = ['root'],
        target_port:int             = 22,
        ssh_key:str                 = '~/.ssh/id_rsa',
        ssh_pw:Optional[str]        = None,
        timeout:float               = 36000,
        max_concurrent_tasks:int    = 10000) -> None:

        full_key_path = os.path.expanduser(ssh_key)
        ssh_key = ssh_key if os.path.exists(full_key_path) else ''

        if not ssh_pw and not ssh_key:
            print(f"ERROR: SSH key not found in {full_key_path}")
            print("Either an SSH key or a passphrase must be provided to perform load testing.")
            sys.exit(2)

        self.user                   = cycle(target_users)
        self.host                   = target_address
        self.port                   = target_port
        self.ssh_key                = os.path.expanduser(ssh_key) if ssh_key is not None else '/'
        self.ssh_pw                 = ssh_pw
        self.timeout                = timeout
        self.max_concurrent_tasks   = max_concurrent_tasks

    def _calculate_stats(self, perf_times:dict, conns, rounds, conns_per_sec:int, conn_wait:int, global_wait:int, graph:bool, stress_type:str):
        stats = {
                "stress_type"       : stress_type,
                "rounds"            : rounds,
                "conns_per_round"   : conns,
                "total_conns"       : conns * rounds,
                "conns_per_sec"     : conns_per_sec,
                "conn_wait"         : conn_wait,
                "global_wait"       : global_wait,
                }
        
        rounds_dict = {}
        for round_name, round_data in perf_times.items():
            total_auth_time     = 0
            total_conn_time     = 0
            max_auth_time       = 0
            max_conn_time       = 0
            min_auth_time       = float('inf')
            min_conn_time       = float('inf')
            total_conns         = len(round_data)
            total_failed        = 0

            for data in round_data.values():
                if data["success"]:
                    auth_time           = data["auth_time"]
                    total_auth_time    += auth_time
                    max_auth_time       = max(max_auth_time, auth_time)
                    min_auth_time       = min(min_auth_time, auth_time)

                    conn_time          = data["conn_time"]
                    total_conn_time    += conn_time
                    max_conn_time       = max(max_conn_time, conn_time)
                    min_conn_time       = min(min_conn_time, conn_time)

                else:
                    total_failed += 1
            try:
                avg_auth_time = total_auth_time / ( total_conns - total_failed )
                avg_conn_time = total_conn_time / ( total_conns - total_failed )

            except ZeroDivisionError:
                avg_auth_time = 0
                avg_conn_time = 0

            rounds_dict[round_name] = {
                    "avg_auth_time"         : avg_auth_time,
                    "avg_conn_time"         : avg_conn_time,
                    "max_auth_time"         : max_auth_time,
                    "max_conn_time"         : max_conn_time,
                    "min_auth_time"         : min_auth_time,
                    "min_conn_time"         : min_conn_time,
                    "failed_conns"          : total_failed,
                    "conn_data"             : round_data
                    }
        stats["round_data"] = (rounds_dict)

        if graph:
            gen_graph(stats)

        return stats


    async def _sftp(self, count:int, user:str = 'root', conn_wait:int = 0, sftp_ls:str = '/') -> dict:
        print(f'id: {count} | Openning SFTP connection for user: {user}')
        try:
            start_time = time.perf_counter()
            async with asyncssh.connect(
                host=self.host, 
                username=user,
                client_keys=[self.ssh_key] if self.ssh_key else None, 
                password=self.ssh_pw,
                port=self.port,
                # Authentication timeout
                login_timeout=0,
                # Authentication timeout + TCP
                connect_timeout=0
            ) as conn:
                auth_time = time.perf_counter() - start_time
                async with conn.start_sftp_client() as sftp:
                    result = await asyncio.wait_for(sftp.listdir(sftp_ls), timeout=self.timeout)
                    if wait:
                        while wait:
                            await asyncio.sleep(0.1)
                    else:
                        await asyncio.sleep(conn_wait)
                    conn.close()
                    total_time = time.perf_counter() - start_time
                    conn_stat = {
                            "id"        : count,
                            "success"   : True,
                            "auth_time" : auth_time,
                            "conn_time" : total_time,
                            "results"   : result,
                            }
                    print(f'id: {conn_stat["id"]} | time: {conn_stat["conn_time"]}')

                    return conn_stat

        except (OSError, asyncssh.Error, asyncio.TimeoutError) as e:
            conn_stat = {
                    "id"        : count,
                    "success"   : False,
                    "auth_time" : None,
                    "conn_time" : None,
                    "results"   : str(e),
                    }
            print(f'id: {conn_stat["id"]} | failed, err: {conn_stat["results"]}')

            return conn_stat


    async def _ssh(self, count:int, user:str = 'root', conn_wait:int = 0) -> dict:
        print(f'id: {count} | Openning SSH connection for user: {user}')
        try:
            start_time = time.perf_counter()
            async with asyncssh.connect(
                host=self.host,
                username=user,
                client_keys=[self.ssh_key] if self.ssh_key else None,
                password=self.ssh_pw,
                port=self.port,
                # Authentication timeout
                login_timeout=0,
                # Authentication timeout + TCP
                connect_timeout=0
            ) as conn:
                auth_time = time.perf_counter() - start_time
                result = await asyncio.wait_for(conn.run('dir'), timeout=self.timeout)
                if wait:
                    while wait:
                        await asyncio.sleep(0.1)
                else:
                    await asyncio.sleep(conn_wait)
                conn.close()
                total_time = time.perf_counter() - start_time
                conn_stat = {
                        "id"        : count,
                        "success"   : True,
                        "auth_time" : auth_time,
                        "conn_time" : total_time,
                        "results"   : result,
                        }
                print(f'id: {conn_stat["id"]} | time: {conn_stat["conn_time"]}')

                return conn_stat

        except (OSError, asyncssh.Error, asyncio.TimeoutError) as e:
            conn_stat = {
                    "id"        : count,
                    "success"   : False,
                    "auth_time" : None,
                    "conn_time" : None,
                    "results"   : str(e),
                    }
            print(f'id: {conn_stat["id"]} | failed, err: {conn_stat["results"]}')

            return conn_stat


    async def _hammer(self, conns:int, conn_wait:int = 0, global_wait:int = 0, conns_per_sec:int = 100, sftp:bool = True, sftp_ls:str = '/') -> dict:
        loop_speed = 1/conns_per_sec

        # Drop all the connections at the exact second
        timer_thread = threading.Thread(target=drop_all_timer, args=(global_wait,))
        timer_thread.start()

        count = 0
        tasks = set()
        perf_times = {}
        while count < conns or tasks:
            if tasks:
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    results = task.result()
                    perf_times[results['id']] = results

            while count < conns and len(tasks) < self.max_concurrent_tasks:
                count += 1
                if sftp:
                    tasks.add(asyncio.create_task(self._sftp(count, next(self.user), conn_wait, sftp_ls=sftp_ls)))
                else:
                    tasks.add(asyncio.create_task(self._ssh(count, next(self.user), conn_wait)))

                # Delay between each connections initiation
                await asyncio.sleep(loop_speed)
        return perf_times


    def stress_sftp(self, conns:int, conn_wait:int, global_wait:int, path:str, conns_per_sec:int, rounds:int, graph:bool = False) -> dict:
        perf_times = {}
        for stress_round in range(rounds):
            stress_round += 1
            print(f"Round {stress_round} started!")
            times = asyncio.run(self._hammer(conns, conn_wait, global_wait, conns_per_sec, sftp=True, sftp_ls=path))
            times = {k: times[k] for k in sorted(times)}
            perf_times[f"round_{stress_round}"] = times

        return self._calculate_stats(perf_times, conns, rounds, conns_per_sec, conn_wait, global_wait, graph, "SFTP")


    def stress_ssh(self, conns:int, conn_wait:int, global_wait:int, conns_per_sec:int, rounds:int, graph:bool = False) -> dict:
        perf_times = {}
        for stress_round in range(rounds):
            stress_round += 1
            print(f"Round {stress_round} started!")
            times = asyncio.run(self._hammer(conns, conn_wait, global_wait, conns_per_sec, sftp=False))
            times = {k: times[k] for k in sorted(times)}
            perf_times[f"round_{stress_round}"] = times

        return self._calculate_stats(perf_times, conns, rounds, conns_per_sec, conn_wait, global_wait, graph, "SSH")


if __name__ == "__main__":
    def validate_names(names):
        if "," in names:
            return [name for name in names.split(",") if name.strip()]
        return [names] if names.strip() else []

    parser = argparse.ArgumentParser(description="SSH Server stress testing utility")
    parser.add_argument("-t", "--target", type=str, help="The target SSH server address.")
    parser.add_argument("-p", "--port", type=int, default=22, help="The target SSH server port.")
    parser.add_argument("-u", "--users", type=validate_names, default="root", help="The target username or a comma separated list of usernames to connect with.")
    parser.add_argument("-P", "--password", type=str, help="Password used to authenticate to the target user.")
    parser.add_argument("-k", "--key", type=str, default="~/.ssh/id_rsa", help="Key used to authenticate the target user.")
    parser.add_argument("-c", "--connections", type=int, default=100, help="Amount of concurrent connections to open at once. (default 100)")
    parser.add_argument("-gw", "--global-wait", type=int, default=0, help="The amount of time in seconds to wait before dropping all the connections at once. This overrides the --connection-timeout parameter. (default disabled)")
    parser.add_argument("-cw", "--connection-wait", type=int, default=0, help="The amount of time to wait in seconds before dropping a connection. (default 0)")
    parser.add_argument("-r", "--rounds", type=int, default=1, help="Repeats the same test with the same parameters, unless the current test fails. (default 1)")
    parser.add_argument("-s", "--speed", type=float, default=100, help="How many connections per second, this is limited by how fast is the machine running the script. (default 100)")
    parser.add_argument("--type", type=str, default="sftp", help="The type of stress test either SFTP or SSH. (default SFTP)")
    parser.add_argument("--path", type=str, default="/", help="The SFTP Path to check when performing load testing")
    parser.add_argument("-o", "--output", type=str, default="", help="Write the results to a file.")
    parser.add_argument("--read", type=str, default="", help="Read results from a file adn visualize them in a graph.")
    parser.add_argument("--graph", action="store_true", help="Visualize the performance data in a graph.")
    args = parser.parse_args()

    if args.read:
        file = args.read
        with open(file, "r") as file:
            json_data = json.load(file)
        gen_graph(json_data)
        sys.exit(0)

    if not args.users:
        print("Missing argument: target user")
        sys.exit(2)

    if not args.target:
        print("Missing argument: target host")
        sys.exit(2)


    print(f"Settings: stress_type: {args.type.lower()} | connections: {args.connections} | global_wait: {args.global_wait} | connection_wait: {args.connection_wait} | speed: {args.speed}/cps")

    ssh_stress_util = SSHstress(target_address=args.target, target_port=args.port, target_users=args.users, ssh_key=args.key, ssh_pw=args.password)
    match args.type.lower():
        case "sftp":
            stats = ssh_stress_util.stress_sftp(conns=args.connections,
                                                conn_wait=args.connection_wait, 
                                                global_wait=args.global_wait, 
                                                conns_per_sec=args.speed,
                                                rounds=args.rounds,
                                                path=args.path,
                                                graph=args.graph)
            if args.output:
                with open(args.output, 'w') as file:
                    json.dump(stats, file, indent=2)

            data = {}
            for round_name, round_stat in stats["round_data"].items():
                round_stat.pop("conn_data", None)
                data[round_name] = round_stat
            print(json.dumps(data, indent=2))

        case "ssh":
            stats = ssh_stress_util.stress_ssh(conns=args.connections, 
                                               conn_wait=args.connection_wait, 
                                               global_wait=args.global_wait, 
                                               conns_per_sec=args.speed,
                                               rounds=args.rounds,
                                               graph=args.graph)
            print(json.dumps(stats, indent=2))

        case _:
            print(f"ERROR: Unknown stress test type: {args.type.lower()}")
            print("The stress test type must be either SSH or SFTP")
            sys.exit(2)

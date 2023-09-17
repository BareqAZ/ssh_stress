# SSH/SFTP Stress Testing Script

This script is designed to assess your server's capacity by testing how many connections it can handle. It can initiate tens of thousands of connections and generate a performance metrics graph for your server.

**Note:** Cryptography and key exchange operations can be resource-intensive. When planning to stress test a server, ensure that your client machine has better hardware specifications than the target server to avoid bottlenecks.

## Usage

1. Create a Python virtual environment:

   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip3 install -r requirements.txt
   ```

2. Test the script with the following example usage:
`ssh_stress.py -u root -p password -t x.x.x.x -c 1000 -s 10 --graph`

In this example, the script will use the credentials "user: root" and "password: password" to initiate 1000 connections at a rate of 10 connections per second to the target host: "x.x.x.x". After the test is complete, a graph will be generated. You can also use the "-output" flag to save the results to a file and then use the "--load" argument to load the results and display a graph.

You can also use public key authentication. If you're using an OpenSSH client and have already set up public key authentication for the target host, this script will automatically use the default key (~/.ssh/id_rsa).

Alternatively, you can specify the public key explicitly using the "-k" argument. For instance:
`ssh_stress.py -u root -k ~/.ssh/id_rsa -t x.x.x.x -p 22 -c 1000 -s 10 --graph`

For more detailed information, please run:
`ssh_stress.py -h`

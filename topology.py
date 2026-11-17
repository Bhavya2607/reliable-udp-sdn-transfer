from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info


class ReliableUDPTopo(Topo):
    def build(self):
        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:04')
        s1 = self.addSwitch('s1', dpid='0000000000000001', protocols='OpenFlow13')
        s2 = self.addSwitch('s2', dpid='0000000000000002', protocols='OpenFlow13')
        s3 = self.addSwitch('s3', dpid='0000000000000003', protocols='OpenFlow13')
        s4 = self.addSwitch('s4', dpid='0000000000000004', protocols='OpenFlow13')
        self.addLink(h1, s1, port1=0, port2=1)
        self.addLink(s1, s2, port1=2, port2=1)
        self.addLink(s1, s3, port1=3, port2=1)
        self.addLink(s2, s4, port1=2, port2=2)
        self.addLink(s3, s4, port1=2, port2=3)
        self.addLink(s4, h2, port1=1, port2=0)


def run():
    topo = ReliableUDPTopo()
    net = Mininet(topo=topo, controller=None, switch=OVSSwitch, autoSetMacs=False, build=True)
    net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)
    net.start()
    info('\n*** Network ready. Initial path should be s1-s2-s4.\n')
    info('*** Start receiver in background: h2 python3 server.py &\n')
    info('*** In another CLI command: h1 python3 client.py sample.txt 10.0.0.2\n')
    info('*** Failure demo: link s1 s2 down   |   Recovery: link s1 s2 up\n\n')
    CLI(net)
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    run()

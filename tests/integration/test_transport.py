import socket
import unittest

from common.transport import UdpTransport


class UdpTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = self.enterContext(UdpTransport(("127.0.0.1", 0)))
        self.client = self.enterContext(UdpTransport(("127.0.0.1", 0)))

    def test_exchanges_binary_data_in_both_directions(self) -> None:
        request = b"\x00\xffhello UDP\x80"
        self.client.send_to(request, self.server.local_address)

        received, sender = self.server.receive()

        self.assertEqual(received, request)
        self.assertEqual(sender, self.client.local_address)

        self.server.send_to(received, sender)
        response, sender = self.client.receive()

        self.assertEqual(response, request)
        self.assertEqual(sender, self.server.local_address)

    def test_preserves_datagram_boundaries(self) -> None:
        self.client.send_to(b"first", self.server.local_address)
        self.client.send_to(b"second", self.server.local_address)

        received = [self.server.receive()[0], self.server.receive()[0]]

        self.assertCountEqual(received, [b"first", b"second"])

    def test_receives_empty_datagram(self) -> None:
        self.client.send_to(b"", self.server.local_address)

        received, sender = self.server.receive()

        self.assertEqual(received, b"")
        self.assertEqual(sender, self.client.local_address)

    def test_identifies_two_clients_and_routes_replies(self) -> None:
        with UdpTransport(("127.0.0.1", 0)) as second_client:
            self.client.send_to(b"client one", self.server.local_address)
            second_client.send_to(b"client two", self.server.local_address)

            received = {}
            for _ in range(2):
                data, sender = self.server.receive()
                received[sender] = data
                self.server.send_to(data, sender)

            self.assertEqual(
                received,
                {
                    self.client.local_address: b"client one",
                    second_client.local_address: b"client two",
                },
            )
            self.assertEqual(self.client.receive()[0], b"client one")
            self.assertEqual(second_client.receive()[0], b"client two")

    def test_raises_timeout_when_no_datagram_arrives(self) -> None:
        with UdpTransport(("127.0.0.1", 0), timeout=0.05) as transport:
            with self.assertRaises(TimeoutError):
                transport.receive()

    def test_interoperates_with_a_plain_udp_socket(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
            peer.settimeout(1.0)
            peer.bind(("127.0.0.1", 0))
            peer.sendto(b"plain UDP", self.server.local_address)

            received, sender = self.server.receive()
            self.assertEqual(received, b"plain UDP")
            self.assertEqual(sender, peer.getsockname())

            self.server.send_to(b"reply", sender)
            response, sender = peer.recvfrom(65535)
            self.assertEqual(response, b"reply")
            self.assertEqual(sender, self.server.local_address)

    def test_context_manager_closes_socket(self) -> None:
        with UdpTransport(("127.0.0.1", 0)) as transport:
            transport.send_to(b"before closing", self.server.local_address)
            self.assertEqual(self.server.receive()[0], b"before closing")

        with self.assertRaises(OSError):
            transport.send_to(b"after closing", self.server.local_address)

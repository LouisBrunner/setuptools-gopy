import unittest

from simple import HelloWorld


class TestGo(unittest.TestCase):
    def test_hello(self):
        self.assertEqual(HelloWorld("gopy"), "Hello, gopy!\n")

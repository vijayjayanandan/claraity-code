import unittest

from src.hello_world import hello_world


class TestHelloWorld(unittest.TestCase):
    def test_hello_world_returns_expected_message(self):
        self.assertEqual(hello_world(), "Hello, World!")


if __name__ == '__main__':
    unittest.main()

import unittest
from src.utils.hello_world import hello_world

class TestHelloWorld(unittest.TestCase):
    def test_hello_world(self):
        result = hello_world()
        self.assertEqual(result, "Hello, World!")

if __name__ == '__main__':
    unittest.main()

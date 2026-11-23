import unittest
class T(unittest.TestCase):
    @unittest.expectedFailure
    def test_AUTH_001_S1_a(self): pass
    def test_AUTH_001_S1_b(self):
        'doc'
        self.skipTest('later')

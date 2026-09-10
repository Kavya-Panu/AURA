import unittest
from brain.conversation_manager import ConversationManager
from brain.conversation_context import ConversationContext

class TestConversation(unittest.TestCase):
    def test_history_accumulates(self):
        c = ConversationContext(max_turns=5)
        c.add_user("q1"); c.add_assistant("a1"); c.add_user("q2")
        msgs = c.messages()
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0], {"role": "user", "content": "q1"})

    def test_bounded_history(self):
        c = ConversationContext(max_turns=2)   # keeps 4 messages
        for i in range(10):
            c.add_user(f"q{i}"); c.add_assistant(f"a{i}")
        self.assertLessEqual(len(c.messages()), 4)

    def test_topic_and_mode(self):
        c = ConversationContext()
        c.set_topic("electronics"); c.set_mode("TEACHER")
        self.assertEqual(c.topic, "electronics")
        self.assertEqual(c.mode, "TEACHER")

    def test_recent_questions(self):
        c = ConversationContext()
        c.add_user("first"); c.add_user("second")
        self.assertEqual(c.recent_questions(), ["first", "second"])

    def test_manager_sessions_isolated(self):
        m = ConversationManager()
        m.get("a").add_user("hello a")
        m.get("b").add_user("hello b")
        self.assertEqual(len(m.get("a").messages()), 1)
        self.assertNotEqual(m.get("a").messages(), m.get("b").messages())

    def test_manager_reset(self):
        m = ConversationManager()
        m.get("s").add_user("x")
        m.reset("s")
        self.assertEqual(m.get("s").messages(), [])

if __name__ == "__main__":
    unittest.main()

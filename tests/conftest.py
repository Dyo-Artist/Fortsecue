import os
import tempfile

TEST_RUNTIME_DIR = tempfile.mkdtemp(prefix="logos_test_")

os.environ.setdefault("LOGOS_STAGING_DIR", os.path.join(TEST_RUNTIME_DIR, "staging"))
os.environ.setdefault("LOGOS_FEEDBACK_DIR", os.path.join(TEST_RUNTIME_DIR, "feedback"))
os.environ.setdefault("LOGOS_SCHEMA_MUTABLE", "0")

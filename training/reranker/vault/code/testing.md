# Testing Python code

Write small, fast unit tests for each function, and keep them independent so they can run in any order.

Use fixtures to share setup such as temporary directories. A test should never depend on files left behind by another test.

Mock only the boundaries you do not control, such as network calls. Over-mocking makes tests pass while the real code is broken.

A failing test should explain what went wrong; assert on specific values rather than on true or false.

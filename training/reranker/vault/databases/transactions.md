# SQL transactions

A transaction groups statements so they either all commit or all roll back. Begin it explicitly, run the statements, then commit.

Isolation levels control what concurrent transactions can see. Serializable is the strictest; read committed allows non-repeatable reads.

If two transactions update the same rows in opposite order they can deadlock. The database aborts one of them, and the application should retry it.

Keep transactions short, and never wait for user input while one is open. See [[databases/indexes]] for making the statements inside them fast.

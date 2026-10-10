# Database indexes

An index lets the database find rows without scanning the whole table, much like the index at the back of a book.

A composite index on two columns helps queries that filter on the first column, or on both, but not on the second column alone.

Every index slows down inserts and updates, because the index must be maintained too. Only index columns that queries actually filter or sort on.

Use the query plan to confirm that a query uses the index you expect.

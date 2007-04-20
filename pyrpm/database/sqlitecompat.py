
ok = False
sqlite = None

try:
    from sqlite3 import *
    ok = True
except ImportError:
    try:
        import sqlite
        from sqlite import *
        ok = True
    except ImportError:
        pass

if sqlite:

    Error = sqlite._sqlite.Error
    DatabaseError = sqlite._sqlite.DatabaseError
    Row = None

    def connect(*args, **kwargs):
        # We currently require utf8 enconding for sqlite2 python
        if not kwargs.has_key('client_encoding'):
            kwargs['client_encoding'] = 'utf8'
        return Connection(*args, **kwargs)

    class Connection(sqlite.Connection):

        def cursor(self):
            return Cursor(sqlite.Connection.cursor(self))

    class Cursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def __getattr__(self, name):
            return getattr(self.cursor, name)

        def ___translate_query(self, query):
            query = query.replace('?', '%s')
            return query

        def execute(self, SQL, *params):
            SQL = self.___translate_query(SQL)
            return self.cursor.execute(SQL, *params)

        def executemany(self, query, param_sequence):
            query = self.___translate_query(query)
            return self.cursor.executemany(SQL, param_sequence)

# vim:ts=4:sw=4:showmatch:expandtab

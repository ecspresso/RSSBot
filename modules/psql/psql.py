import os
import psycopg2

class ConnectionError(Exception):
    def __init__(self, message):
        super().__init__(message)

class PSQL:
    def __init__(self, host, user, password, database, port=5432):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.database = database

    def _connect(self):
        self.connection = psycopg2.connect(
            host = self.host,
            user = self.user,
            password = self.password,
            port = self.port,
            database = self.database
        )
        self.cursor = self.connection.cursor()


    def _close(self):
        try:
            self.connection.close()
            self.cursor.close()
        except AttributeError:
            pass

    def select(self, columns, table, condition=None):
        statement = f"SELECT {columns} FROM {table}"
        if condition is not None:
            statement += f" {condition}"

        try:
            self._connect()
            self.cursor.execute(statement)
            return self.cursor.fetchall()
        except psycopg2.OperationalError as error:
            raise error
        finally:
            self._close()

    def insert(self, table, columns, values):
        statement = f"INSERT INTO {table} ({columns}) VALUES ({values})"

        try:
            self._connect()
            self.cursor.execute(statement)
            self.connection.commit()
        except psycopg2.OperationalError as error:
            raise error
        finally:
            self._close()


    def update(self, table, values, condition=None):
        statement = f"UPDATE {table} SET {values}"
        if condition is not None:
            statement += f" {condition}"

        try:
            self._connect()
            self.cursor.execute(statement)
            self.connection.commit()
        except psycopg2.OperationalError as error:
            raise error
        finally:
            self._close()
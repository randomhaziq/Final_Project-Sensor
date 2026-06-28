import sqlite3

conn = sqlite3.connect("iot_data.db")
c = conn.cursor()

c.execute("SELECT * FROM sensor_data")
rows = c.fetchall()

for row in rows:
    print(row)

conn.close()
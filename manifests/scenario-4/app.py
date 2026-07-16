from flask import Flask, jsonify
import psycopg2, os, math
app = Flask(__name__)
def db(): return psycopg2.connect(host="db", user="postgres", password=os.environ["PGPASSWORD"])
@app.route("/api/books")
def books():
    with db() as c, c.cursor() as cur:
        cur.execute("SELECT title, author FROM books ORDER BY id")
        return jsonify([{"title": t, "author": a} for t, a in cur.fetchall()])
@app.route("/api/work")
def work():
    x = 0.0001
    for _ in range(1_500_000): x = math.sqrt(x + 1.7)   # ~200ms of honest CPU burn
    return jsonify({"pod": os.environ.get("HOSTNAME"), "result": x})

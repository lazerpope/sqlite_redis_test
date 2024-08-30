import random
from flask import Flask, request, jsonify
import sqlite3
import redis
import json
import os
from datetime import datetime, timedelta

DATABASE = "db.sqlite3"
DATABASE_ROW_COUNT = 1000
PROGREV = True
PER_PAGE = 20  # сколько статей показывается на странице
PRELOAD_PAGES = 120  # сколько страничек предзагрузить в редис


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def check_file_exists(file_path):
    try:
        if os.path.exists(file_path):
            print(f"The file {file_path} exists.")
            return True
        else:
            print(f"The file {file_path} does not exist.")
            return False
    except Exception as e:
        print(f"An error occurred: {e}")
        return False


if check_file_exists(DATABASE):
    print("База данных SQLITE найдена")
else:
    print("База данных SQLITE НЕ найдена")

    print(f"Генерируем базу данных на {DATABASE_ROW_COUNT} строк ...")

    alphabet = "ABCDEFGHIJKLMNOPQRSTXYZ "
    import random

    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        """CREATE TABLE "articles" 
        ("TITLE" TEXT, "TEXT" TEXT, "VIEWS" INTEGER DEFAULT 0, "ID" INTEGER PRIMARY KEY, created_at DATETIME)
        """
    )
    db.commit()
   
    for i in range(DATABASE_ROW_COUNT):
        title = "".join(
            [random.choice(alphabet) for i in range(random.randint(20, 100))]
        )
        text = "".join(
            [random.choice(alphabet) for i in range(random.randint(500, 2000))]
        )
        start_date = datetime.now() - timedelta(days=365)
        end_date = datetime.now()
        random_date = start_date + timedelta(
            seconds=random.randint(0, int((end_date - start_date).total_seconds())),
        )
        date = random_date.strftime("%Y-%m-%d %H:%M:%S")
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO articles (title, text, created_at) VALUES (?, ?, ?)",
            (title, text, date),
        )
    db.commit()
    db.close()
    print("База данных SQLITE сгенерирована")


app = Flask(__name__)
# 127.0.0.1:6379
red = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
red_pages = redis.Redis(host="localhost", port=6379, db=1, decode_responses=True)

ping = red.ping()
print("redis ", "подключен" if ping else "ОШИБКА")

red.flushdb()  # Delete all keys in the current database
red_pages.flushdb()  # Delete all keys in the current database
print("redis ", "ПОЛНОСТЬЮ ОЧИЩЕН!!!")


# Функция для получения подключения к базе данных


def progrev_stranichec():
    if not PROGREV:
        print("СТРАНИЦЫ НЕ ЗАГРУЖЕНЫ В РЕДИС")
        return

    print("СТРАНИЦЫ ЗАГРУЖАЮТСЯ ...")

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            SELECT id FROM articles
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (PER_PAGE * PRELOAD_PAGES,),
        )
        articles = cursor.fetchall()
    except:
        articles = None
    finally:
        db.close()

    if articles is None:
        print("No articles found")
        return

    article_ids = [article[0] for article in articles]
    chunks = [
        article_ids[i : i + PER_PAGE] for i in range(0, len(article_ids), PER_PAGE)
    ]

    for i, chunk in enumerate(chunks):
        red_pages.hset(str(i + 1), "article_ids", json.dumps(chunk))

    print("СТРАНИЦЫ ЗАГРУЖЕНЫ")


progrev_stranichec()


@app.route("/onlysql/article/<int:article_id>", methods=["GET"])
def get_article(article_id):

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM articles WHERE articles.id = ?", (article_id,))
        article = cursor.fetchone()
        if article:
            # Add the article to Redis
            article = dict(article)
    except Exception as e:
        print(e)
        article = None
    finally:
        db.close()

    if article is None:
        return jsonify({"error": "Article not found"}), 404

    return jsonify(article)


@app.route("/sqlandredis/article/<int:article_id>", methods=["GET"])
def get_article_red(article_id):

    article = red.hgetall(str(article_id))
    if article:
        # If it's in Redis, return it
        print("cashed article!")
        return jsonify(article)

    # If it's not in Redis, get it from SQL
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT * FROM articles WHERE articles.id = ?", (article_id,))
        article = cursor.fetchone()
        if article:
            # Add the article to Redis
            article = dict(article)

            red.hset(str(article_id), mapping=article)
    except Exception as e:
        print(e)
        article = None
    finally:
        db.close()

    if article is None:
        return jsonify({"error": "Article not found"}), 404

    return jsonify(article)


# прогрев страничек


@app.route("/onlysql/page/<int:page>", methods=["GET"])
def get_articles(page):

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            SELECT * FROM articles
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """,
            (PER_PAGE, (page - 1) * PER_PAGE),
        )
        articles = cursor.fetchall()
    except:
        articles = None
    finally:
        db.close()

    if articles is None:
        return jsonify({"error": "No articles found"}), 404

    articles = [dict(article) for article in articles]

    return jsonify(articles)


@app.route("/sqlandredis/page/<int:page>", methods=["GET"])
def get_articles_red(page):
    if page < PRELOAD_PAGES:
        # Get article IDs from Redis
        article_ids = red_pages.hget(str(page), "article_ids")[1:-2].split(",")
        article_ids = [int(article_id) for article_id in article_ids]
        if article_ids:
            # Get articles from DB by IDs
            db = get_db()
            cursor = db.cursor()
            try:
                cursor.execute(
                    """
                    SELECT * FROM articles
                    WHERE id IN (%s)
                """
                    % ",".join(["?"] * len(article_ids)),
                    article_ids,
                )
                articles = cursor.fetchall()
            except:
                articles = None
            finally:
                db.close()

            if articles is None:
                return jsonify({"error": "No articles found"}), 404

            articles = [dict(article) for article in articles]
            return jsonify(articles)

    # If page is 10 or more, or if Redis doesn't have the page
    # Get articles from DB using LIMIT and OFFSET

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            SELECT * FROM articles
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """,
            (PER_PAGE, (page - 1) * PER_PAGE),
        )
        articles = cursor.fetchall()
    except:
        articles = None
    finally:
        db.close()

    if articles is None:
        return jsonify({"error": "No articles found"}), 404

    articles = [dict(article) for article in articles]
    return jsonify(articles)


if __name__ == "__main__":

    app.run(debug=True)

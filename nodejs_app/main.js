const express = require('express');
const app = express();
const sqlite3 = require('sqlite3').verbose();


// Assuming you have a getDb function that returns a SQLite database object
const getDb = () => {
  return new sqlite3.Database('../db.sqlite3');
};

// Assuming you have a Redis client


app.get('/onlysql/article/:article_id', (req, res) => {
    console.log(req. originalUrl);
    
  const articleId = req.params.article_id;
  const db = getDb();

  db.get('SELECT * FROM articles WHERE id = ?', articleId, (err, row) => {
    if (err) {
      console.error(err);
      res.status(404).json({ error: 'Article not found' });
    } else if (!row) {
      res.status(404).json({ error: 'Article not found' });
    } else {
      const article = row;
     
      res.json(article);
    }
  });


  db.close();
});

const port = 5000;
app.listen(port, () => {
  console.log(`Server listening on port ${port}`);
});

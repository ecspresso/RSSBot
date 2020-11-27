# RSSBot

## Setup
1. Install PostgreSQL
2. Connect to PSQL and create a new user to be used by the bot.
3. Connect to PSQL as the new user.
4. Create the database and tables:
```SQL
CREATE DATABASE RSS;
CREATE TABLE mangadex (user_id BIGINT NOT NULL PRIMARY KEY, rss_feed TEXT NOT NULL, chapter_id TEXT, channel_id BIGINT);
CREATE TABLE rss_feeds (id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, url TEXT NOT NULL, latest TEXT, channel_id BIGINT, name TEXT NOT NULL);
```
5. Install all requirements:
```
python3 -m pip install -r requirements.txt
```
6. Modify the `psql_sample` file with connection details for the database and the newly created user and save as `psql`.
7. Run bot.

## Mangadex
Add your RSS url found under Follows to be notifed of any new chapters:
<br>
`!setdexur https://mangadex.org/rss/follows/....`

## RSS
Add and RSS url to be notified of updates:
<br>
`!setrss "Name of feed" https://example.com/....`
<br>
`!setrss NameOfFeed https://example.com/....`

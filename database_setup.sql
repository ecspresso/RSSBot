CREATE DATABASE RSS;
CREATE TABLE mangadex (user_id BIGINT NOT NULL PRIMARY KEY, rss_feed TEXT NOT NULL, chapter_id TEXT, channel_id BIGINT);
CREATE TABLE rss_feeds (id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, url TEXT NOT NULL, latest TEXT, channel_id BIGINT);

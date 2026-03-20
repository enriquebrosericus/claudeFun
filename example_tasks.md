# Example Agent Tasks

Run the agent with a custom prompt:

```bash
pip install -r requirements.txt
python scraper_agent.py "your task here"
```

## Example prompts

### E-commerce price tracker
```
Build a price tracker for an e-commerce site that scrapes product prices every 5 minutes,
exposes a Gauge metric 'product_price_usd' with labels for product_id and name,
and creates a Grafana dashboard showing price history and alerting when price drops >10%.
```

### GitHub API monitor
```
Build a Prometheus exporter that polls the GitHub API for a list of repos and exposes:
- open_issues_total (Gauge, labels: repo, label)
- stars_total (Gauge, labels: repo)
- last_commit_age_seconds (Gauge, labels: repo, branch)
Include a Grafana dashboard with a repo health overview.
```

### Website uptime monitor
```
Create a scraper that checks a list of URLs every 60 seconds and exposes:
- http_response_seconds (Histogram, labels: url, status_code)
- http_up (Gauge 0/1, labels: url)
- ssl_cert_expiry_seconds (Gauge, labels: url)
Generate a Grafana dashboard with SLA uptime stats and latency percentiles.
```

### Reddit post tracker
```
Scrape r/programming for top posts every 10 minutes. Expose:
- reddit_post_score (Gauge, labels: subreddit, flair)
- reddit_post_comments_total (Gauge, labels: subreddit)
- reddit_posts_scraped_total (Counter, labels: subreddit)
Build a Grafana dashboard showing trending flairs and score distributions.
```

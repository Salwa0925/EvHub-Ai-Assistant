from sites.evclinic.crawler import EvClinicCrawler


def test_parse_article(monkeypatch):
    sample_html = """
    <html>
      <body>
        <h1>Test Title</h1>
        <div class="content-date-comments">
          <div class="date-meta">15 June 2023</div>
        </div>
        <div class="futurio-content single-content">
          <p>This is an English paragraph that clearly contains the word the and other english words.</p>
          <p>Un párrafo en español.</p>
          <figure class="wp-block-image size-large">
            <img src="/wp-content/uploads/pic.jpg" data-src="https://i0.wp.com/example/pic.jpg" />
          </figure>
          <p>Faults:</p>
          <ul class="wp-block-list">
            <li>P1570,</li>
            <li>P1446,</li>
          </ul>
          <p>Part numbers:</p>
          <ul class="wp-block-list">
            <li>1E100RMX0132,</li>
            <li>AEV6804A,</li>
          </ul>
        </div>

        <div class="comment-body">
          <div class="comment-author vcard"><cite class="fn">goran crvchevski</cite></div>
          <div class="comment-meta commentmetadata"><a href="#">28 August 2024 at 10:16</a></div>
          <p>Dobar Dan - comment text</p>
        </div>
      </body>
    </html>
    """

    # Monkeypatch the network call to return our sample HTML
    monkeypatch.setattr(EvClinicCrawler, "get", lambda self, url, params=None: sample_html)

    crawler = EvClinicCrawler(delay=0)
    article = crawler.parse_article("https://evclinic.eu/test-article")

    assert article["title"] == "Test Title"
    assert "English paragraph" in article["content"]
    assert any("wp-content/uploads/pic.jpg" in img or "example/pic.jpg" in img for img in article["images"])
    assert article["published_date"] == "15 June 2023"
    assert article["fault_codes"] == ["P1570", "P1446"]
    assert article["part_numbers"] == ["1E100RMX0132", "AEV6804A"]
    assert len(article["comments"]) >= 1
    first_comment = article["comments"][0]
    assert first_comment["author"] == "goran crvchevski"
    assert "comment text" in first_comment["text"]
    assert article["url"] == "https://evclinic.eu/test-article"

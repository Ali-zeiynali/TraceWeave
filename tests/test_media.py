from traceweave.fetcher import extract_media_links


def test_extract_media_links_deduplicates_and_keeps_region_hints() -> None:
    html = b"""
    <html><head><meta property="og:image" content="/hero.png"></head>
    <body>
      <img src="/hero.png" alt="Project Lantern board">
      <img data-src="images/screen.webp" alt="Roadmap screen" width="1200" height="800">
      <img src="data:image/png;base64,nope">
    </body></html>
    """
    rows = extract_media_links(html, "https://example.com/posts/1")
    assert [row.url for row in rows] == [
        "https://example.com/hero.png",
        "https://example.com/posts/images/screen.webp",
    ]
    assert rows[1].alt == "Roadmap screen"
    assert (rows[1].width, rows[1].height) == (1200, 800)

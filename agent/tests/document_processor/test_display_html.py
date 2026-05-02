from service.document_processor.display_html import build_display_html


def test_build_display_html_preserves_docling_shell_css_and_styles():
    raw_html = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>source</title>
        <style>
          body { color: red; }
          .page { margin: 1em; }
          .unused { color: blue; }
        </style>
      </head>
      <body>
        <div class="page" style="padding: 1em">
          <p>正文</p>
        </div>
      </body>
    </html>
    """

    result = build_display_html(raw_html)

    assert "<html>" in result
    assert "<head>" in result
    assert "<body>" in result
    assert 'class="page"' in result
    assert 'style="padding: 1em"' in result
    assert 'id="dp-p-1"' in result
    assert "body {" in result
    assert ".page {" in result
    assert ".unused {" not in result
    assert ".dp-evidence-highlight" in result


def test_build_display_html_assigns_ids_to_same_semantic_tags():
    raw_html = """
    <html><body>
      <h2>标题</h2>
      <p>正文</p>
      <table><tr><th>列</th></tr><tr><td>值</td></tr></table>
    </body></html>
    """

    result = build_display_html(raw_html)

    assert 'id="dp-h2-1"' in result
    assert 'id="dp-p-1"' in result
    assert 'id="dp-table-1"' in result
    assert 'id="dp-tr-1"' in result
    assert 'id="dp-tr-2"' in result


def test_build_display_html_keeps_existing_ids():
    raw_html = '<html><body><p id="source-p">正文</p><p>第二段</p></body></html>'

    result = build_display_html(raw_html)

    assert 'id="source-p"' in result
    assert 'id="dp-p-1"' in result

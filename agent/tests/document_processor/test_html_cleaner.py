from service.document_processor.html_cleaner import clean_semantic_html


def test_clean_semantic_html_removes_page_shell_and_attributes_only():
    raw_html = """
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="UTF-8">
        <style>.page { color: red; }</style>
        <script>ignored()</script>
      </head>
      <body>
        <div class="page">
          <p class="title" style="font-weight: bold">标题</p>
          <span>行内噪声</span>
          <table class="docling-table" style="width: 100%">
            <tr><th style="color: red">楼栋</th><th>房间</th></tr>
            <tr><td data-x="1">18栋</td><td>212</td></tr>
          </table>
        </div>
      </body>
    </html>
    """

    assert clean_semantic_html(raw_html) == (
        '<div><p id="dp-p-1">标题</p><span>行内噪声</span>'
        '<table id="dp-table-1"><tr id="dp-tr-1">'
        '<th>楼栋</th><th>房间</th>'
        '</tr><tr id="dp-tr-2"><td>18栋</td>'
        '<td>212</td></tr></table></div>'
    )


def test_clean_semantic_html_preserves_rowspan_and_colspan():
    raw_html = """
    <body>
      <table>
        <tr>
          <th colspan="2" class="ignored">学生信息</th>
        </tr>
        <tr>
          <td rowspan="2" style="color:red">18栋</td>
          <td>212</td>
        </tr>
        <tr><td>214</td></tr>
      </table>
    </body>
    """

    assert clean_semantic_html(raw_html) == (
        '<table id="dp-table-1"><tr id="dp-tr-1">'
        '<th colspan="2">学生信息</th></tr>'
        '<tr id="dp-tr-2"><td rowspan="2">18栋</td>'
        '<td>212</td></tr><tr id="dp-tr-3">'
        '<td>214</td></tr></table>'
    )


def test_clean_semantic_html_keeps_empty_table_cells_for_column_alignment():
    raw_html = """
    <body>
      <table>
        <tr><th>楼栋</th><th>房间</th><th>平均分</th><th>模范/文明</th></tr>
        <tr><td>18栋</td><td>101</td><td>84.5</td><td></td></tr>
      </table>
    </body>
    """

    assert clean_semantic_html(raw_html) == (
        '<table id="dp-table-1"><tr id="dp-tr-1">'
        '<th>楼栋</th><th>房间</th>'
        '<th>平均分</th><th>模范/文明</th></tr>'
        '<tr id="dp-tr-2"><td>18栋</td>'
        '<td>101</td><td>84.5</td>'
        '<td></td></tr></table>'
    )


def test_clean_semantic_html_keeps_existing_ids():
    raw_html = """
    <body>
      <h1 id="source-title" class="ignored">通知</h1>
      <p id="source-p">正文</p>
    </body>
    """

    assert clean_semantic_html(raw_html) == (
        '<h1 id="source-title">通知</h1>\n'
        '<p id="source-p">正文</p>'
    )


def test_clean_semantic_html_generates_unique_row_ids_around_existing_ids():
    raw_html = """
    <body>
      <table id="source-table">
        <tr id="dp-tr-1"><th>姓名</th></tr>
        <tr><td>张三</td></tr>
        <tr id="source-row"><td>李四</td></tr>
        <tr><td>王五</td></tr>
      </table>
    </body>
    """

    assert clean_semantic_html(raw_html) == (
        '<table id="source-table"><tr id="dp-tr-1"><th>姓名</th></tr>'
        '<tr id="dp-tr-2"><td>张三</td></tr>'
        '<tr id="source-row"><td>李四</td></tr>'
        '<tr id="dp-tr-3"><td>王五</td></tr></table>'
    )


def test_clean_semantic_html_does_not_filter_docling_content_nodes():
    raw_html = """
    <body>
      <p>   </p>
      <ul><li>第一条</li><li> </li></ul>
      <br>
    </body>
    """

    assert clean_semantic_html(raw_html) == (
        '<p id="dp-p-1"></p>\n'
        '<ul id="dp-ul-1"><li id="dp-li-1">第一条</li>'
        '<li id="dp-li-2"></li></ul>\n'
        '<br>'
    )

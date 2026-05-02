from service.document_processor.table_merger import merge_continued_tables


def test_merge_adjacent_continued_tables_with_data_like_first_row():
    raw_html = """
    <table>
      <tbody>
        <tr><th>楼栋</th><th>房间</th><th>平均分</th><th>模范/文明</th></tr>
        <tr><td>18栋</td><td>219</td><td>87.33</td><td></td></tr>
      </tbody>
    </table>
    <table>
      <tbody>
        <tr><th>18栋</th><th>220</th><th>85.67</th><td></td></tr>
        <tr><td>18栋</td><td>221</td><td>84.92</td><td></td></tr>
      </tbody>
    </table>
    """

    merged = merge_continued_tables(raw_html)

    assert merged.count("<table") == 1
    assert "<td>220</td>" in merged
    assert "<td>221</td>" in merged
    assert "<th>18栋</th>" not in merged


def test_does_not_merge_when_second_table_has_real_header():
    raw_html = """
    <table>
      <tr><th>楼栋</th><th>房间</th></tr>
      <tr><td>18栋</td><td>219</td></tr>
    </table>
    <table>
      <tr><th>姓名</th><th>学院</th></tr>
      <tr><td>张三</td><td>计算机学院</td></tr>
    </table>
    """

    merged = merge_continued_tables(raw_html)

    assert merged.count("<table") == 2
    assert "<th>姓名</th>" in merged


def test_does_not_merge_when_paragraph_between_tables():
    raw_html = """
    <table>
      <tr><th>楼栋</th><th>房间</th></tr>
      <tr><td>18栋</td><td>219</td></tr>
    </table>
    <p>新的名单</p>
    <table>
      <tr><th>18栋</th><th>220</th></tr>
      <tr><td>18栋</td><td>221</td></tr>
    </table>
    """

    merged = merge_continued_tables(raw_html)

    assert merged.count("<table") == 2
    assert "<p>新的名单</p>" in merged


def test_merge_multiple_continuation_tables():
    raw_html = """
    <table>
      <tr><th>楼栋</th><th>房间</th><th>平均分</th><th>模范/文明</th></tr>
      <tr><td>18栋</td><td>219</td><td>87.33</td><td></td></tr>
    </table>
    <table>
      <tr><th>18栋</th><th>220</th><th>85.67</th><td></td></tr>
      <tr><td>18栋</td><td>221</td><td>84.92</td><td></td></tr>
    </table>
    <table>
      <tr><th>18栋</th><th>411</th><th>84.83</th><td></td></tr>
      <tr><td>18栋</td><td>412</td><td>84.42</td><td></td></tr>
    </table>
    """

    merged = merge_continued_tables(raw_html)

    assert merged.count("<table") == 1
    assert "<td>220</td>" in merged
    assert "<td>411</td>" in merged
    assert "<td>412</td>" in merged

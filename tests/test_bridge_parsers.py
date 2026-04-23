from bridge import clean_html, extract_reply_content


class TestCleanHtml:
    def test_empty(self):
        assert clean_html("") == ""
        assert clean_html(None) == ""

    def test_plain_text(self):
        assert clean_html("<p>olá mundo</p>").strip() == "olá mundo"

    def test_strips_images(self):
        out = clean_html('<p>texto <img src="http://x/y.jpg" alt="x"></p>')
        assert "img" not in out.lower()
        assert "olá" not in out
        assert "texto" in out

    def test_br_becomes_newline(self):
        out = clean_html("linha1<br>linha2<br>linha3")
        assert "linha1" in out and "linha2" in out and "linha3" in out
        assert out.count("\n") >= 2

    def test_blockquote_quoting_pattern(self):
        html = '<blockquote>Quoting @alice: olá pessoal</blockquote>\n<p>minha resposta</p>'
        out = clean_html(html)
        assert "[quote=alice]" in out
        assert "olá pessoal" in out
        assert "[/quote]" in out
        assert "minha resposta" in out

    def test_blockquote_citando_pt(self):
        html = '<blockquote>Citando @bob: mensagem original</blockquote>'
        out = clean_html(html)
        assert "[quote=bob]" in out
        assert "mensagem original" in out

    def test_blockquote_short_form(self):
        html = '<blockquote>@carol: texto curto</blockquote>'
        out = clean_html(html)
        assert "[quote=carol]" in out
        assert "texto curto" in out

    def test_blockquote_unknown_author_fallback(self):
        html = '<blockquote>só texto sem formato reconhecido</blockquote>'
        out = clean_html(html)
        assert "[quote=Alguém]" in out

    def test_nested_quotes_outer_only(self):
        html = (
            '<blockquote>Quoting @alice: bla'
            '<blockquote>Quoting @bob: inner</blockquote>'
            '</blockquote>'
            '<p>resposta</p>'
        )
        out = clean_html(html)
        assert out.count("[quote=") == 1
        assert "resposta" in out

    def test_collapses_multiple_blanks(self):
        out = clean_html("<p>a</p><p></p><p></p><p></p><p>b</p>")
        assert "\n\n\n" not in out

    def test_div_with_quote_class(self):
        html = '<div class="quote-box">Quoting @dave: oi</div>'
        out = clean_html(html)
        assert "[quote=dave]" in out


class TestExtractReplyContent:
    def test_bbcode_quote_returns_tail(self):
        text = "[quote=alice]texto citado[/quote]\nminha resposta"
        assert extract_reply_content(text) == "minha resposta"

    def test_bbcode_quote_no_tail_returns_empty(self):
        text = "[quote=alice]só citação[/quote]"
        assert extract_reply_content(text) == ""

    def test_raw_quoting_double_newline_keeps_tail(self):
        text = "Quoting @bob: a citação aqui\n\nreply abaixo"
        assert extract_reply_content(text) == "reply abaixo"

    def test_raw_quoting_single_newline_returns_empty(self):
        text = "Quoting @bob: citação sem reply"
        assert extract_reply_content(text) == ""

    def test_text_without_quote_is_returned_asis(self):
        text = "sem nenhuma citação aqui"
        assert extract_reply_content(text) == text

    def test_strips_malformed_closing_tag(self):
        text = "[quote=x]c[*/quote]\ntail"
        out = extract_reply_content(text)
        assert "[*/quote]" not in out

    def test_old_style_quoted_line(self):
        text = '@eve: "linha citada"\n\nminha resposta longa'
        out = extract_reply_content(text)
        assert out == "minha resposta longa"

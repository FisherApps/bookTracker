"""Tests for src.parse against saved HTML fixtures."""

from pathlib import Path

import pytest

from src.parse import ParseError, parse_product_page

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class TestJFKFixture:
    @pytest.fixture()
    def parsed(self):
        html = (FIXTURES / "jfk.html").read_text()
        return parse_product_page(html, asin="B0GY7T45YS")

    def test_title(self, parsed):
        assert parsed.title == "The Life of John Kennedy (Presidential Chronicles - Individual)"

    def test_author(self, parsed):
        assert parsed.author == "David Fisher"

    def test_overall_rank(self, parsed):
        overall = [r for r in parsed.ranks if r.category_id == "books"]
        assert len(overall) == 1
        assert overall[0].rank == 857576
        assert overall[0].category_name == "Books"

    def test_sub_rank_executive_government(self, parsed):
        entry = [r for r in parsed.ranks if r.category_id == "16023131"]
        assert len(entry) == 1
        assert entry[0].rank == 698
        assert "United States Executive Government" in entry[0].category_name

    def test_sub_rank_us_presidents(self, parsed):
        entry = [r for r in parsed.ranks if r.category_id == "9681307011"]
        assert len(entry) == 1
        assert entry[0].rank == 859
        assert "US Presidents" in entry[0].category_name

    def test_sub_rank_us_history(self, parsed):
        entry = [r for r in parsed.ranks if r.category_id == "4853"]
        assert len(entry) == 1
        assert entry[0].rank == 14187
        assert "United States History (Books)" in entry[0].category_name

    def test_book_format(self, parsed):
        assert parsed.book_format == "Hardcover"

    def test_total_rank_count(self, parsed):
        assert len(parsed.ranks) == 4  # 1 overall + 3 sub


class TestNoSubRanks:
    @pytest.mark.skip(reason="fixture not yet collected")
    def test_book_with_no_sub_ranks(self):
        pass


class TestCaptchaPage:
    @pytest.mark.skip(reason="fixture not yet collected")
    def test_captcha_raises_parse_error(self):
        pass

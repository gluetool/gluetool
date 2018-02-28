# pylint: disable=blacklisted-name

import pytest
from mock import MagicMock

import urlnorm

from gluetool.utils import treat_url


@pytest.mark.parametrize('url, expected', [
    # Add more patterns bellow when necessary
    ('HTTP://FoO.bAr.coM././foo/././../foo/index.html', 'http://foo.bar.com/foo/index.html'),
    # urlnorm cannot handle localhost but treat_url should handle such situation
    ('http://localhost/index.html', 'http://localhost/index.html')
])
def test_sanity(url, expected):
    assert treat_url(url) == expected


def test_urlnorm_error(monkeypatch):
    monkeypatch.setattr(urlnorm, 'norm', MagicMock(side_effect=urlnorm.InvalidUrl))

    with pytest.raises(urlnorm.InvalidUrl):
        treat_url('dummy url')

    # pylint: disable=no-member
    urlnorm.norm.assert_called_once_with('dummy url')


def test_strip(monkeypatch):
    monkeypatch.setattr(urlnorm, 'norm', MagicMock(return_value=('   so much whitespace   ')))

    assert treat_url('http://foo.bar.com/') == 'so much whitespace'

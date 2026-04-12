"""MkDocs hook to rewrite README language links for the built site.

Runs after markdown rendering (including pymdownx.snippets) so that
links inside --8<-- included files are also rewritten.
"""


def on_page_content(html, page, config, files, **kwargs):
    """Rewrite ./README.md and ./README.ko.md hrefs to MkDocs site paths."""
    html = html.replace('href="./README.md"', 'href="./"')
    html = html.replace('href="./README.ko.md"', 'href="./ko/"')
    return html

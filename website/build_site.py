"""Build the RVTSS website.

    python website/build_site.py                 # regenerate website/manual.html from docs/USER_MANUAL.md
    python website/build_site.py --dist _site    # also assemble a deployable site (pages + media) in _site/

Needs the `markdown` package (pip install markdown) to regenerate manual.html; without it the committed
manual.html is used as is.
"""
import argparse, html, os, re, shutil
try:
    import markdown
except ImportError:
    markdown = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'website')
REPO = 'https://github.com/souhaibsmadi42/RVTSS_MCP/blob/main/'
MEDIA = {  # repo file -> published path
    'media/rvtss-tutorial.mp4': 'media/rvtss-tutorial.mp4',
    'media/rvtss-tutorial-poster.jpg': 'media/rvtss-tutorial-poster.jpg',
    'media/tutorial-src/captions.vtt': 'media/rvtss-tutorial.vtt',
}


def slug(value, separator='-'):
    # GitHub-style anchors: drop punctuation, then each space becomes one hyphen
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    return re.sub(r'\s', separator, value)


def rewrite_links(body):
    """Point the manual's repo-relative links at the website (media, manual) or at GitHub (everything else)."""
    def fix(m):
        href = m.group(1)
        if re.match(r'^(https?:|#|mailto:)', href):
            return m.group(0)
        path = os.path.normpath(os.path.join('docs', href)).replace(os.sep, '/')
        if path in MEDIA:
            return f'href="{MEDIA[path]}"'
        return f'href="{REPO}{path}"'
    return re.sub(r'href="([^"]+)"', fix, body)


def build_manual():
    src = open(os.path.join(ROOT, 'docs', 'USER_MANUAL.md'), encoding='utf-8').read()
    # the page header carries the title; drop the markdown H1 and the hand-written contents list (the sidebar replaces it)
    src = re.sub(r'^# .*\n', '', src, count=1)
    src = re.sub(r'\n## Contents\n.*?\n---\n', '\n', src, count=1, flags=re.S)
    md = markdown.Markdown(extensions=['tables', 'fenced_code', 'toc', 'sane_lists'],
                           extension_configs={'toc': {'slugify': slug, 'toc_depth': '2'}})
    body = rewrite_links(md.convert(src))
    # wrap code blocks so the shared copy-button script finds them
    body = re.sub(r'<pre><code(?: class="language-(\w+)")?>', lambda m: '<div class="code">' + (f'<span class="lang">{m.group(1)}</span>' if m.group(1) else '') + '<pre><code>', body)
    body = body.replace('</code></pre>', '</code></pre></div>')
    body = re.sub(r'<table>', '<div class="table-wrap"><table>', body).replace('</table>', '</table></div>')
    toc = ''.join(f'<li><a href="#{t["id"]}">{html.escape(t["name"])}</a></li>' for t in md.toc_tokens)
    tpl = open(os.path.join(WEB, 'manual.template.html'), encoding='utf-8').read()
    out = tpl.replace('{{TOC}}', toc).replace('{{BODY}}', body)
    with open(os.path.join(WEB, 'manual.html'), 'w', encoding='utf-8') as f:
        f.write(out)
    print('wrote website/manual.html')


def build_dist(dist):
    os.makedirs(os.path.join(dist, 'media'), exist_ok=True)
    for name in ('index.html', 'manual.html', 'style.css'):
        shutil.copy2(os.path.join(WEB, name), os.path.join(dist, name))
    for src, dst in MEDIA.items():
        shutil.copy2(os.path.join(ROOT, src), os.path.join(dist, dst))
    open(os.path.join(dist, '.nojekyll'), 'w').close()
    print('assembled', dist)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dist', help='assemble a deployable site in this folder')
    a = ap.parse_args()
    if markdown:
        build_manual()
    else:
        print('markdown not installed: keeping the committed website/manual.html')
    if a.dist:
        build_dist(a.dist)

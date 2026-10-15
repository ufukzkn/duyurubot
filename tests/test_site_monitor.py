import unittest

from scraper.site_monitor import extract_detail, extract_list_links, filter_links, load_sites_yaml


class SiteMonitorTests(unittest.TestCase):
    def test_new_list_uses_only_title_and_deduplicates_urls(self):
        site = load_sites_yaml()[0]
        html = '''<a class="estu-announcement-item" href="/tr/Duyuru/Detay/ornek">
          <time>15 Eki</time><span class="estu-announcement-item__body">
          <span>Kurum İçi</span><strong>Örnek duyuru başlığı</strong>
          <span class="estu-announcement-excerpt">Özet metin</span></span></a>
          <a class="estu-announcement-item" href="/tr/Duyuru/Detay/ornek">Tekrar</a>'''
        items = extract_list_links(html, '', site['item_link_selector'], site['url'])
        items = filter_links(items, site['include_url_regex'])
        self.assertEqual(items, [{'title': 'Örnek duyuru başlığı',
                                 'url': 'https://www.eskisehir.edu.tr/tr/Duyuru/Detay/ornek'}])

    def test_new_detail_excludes_sidebar_and_reads_article_date(self):
        html = '''<main><aside><h2>Son Duyurular</h2><time>01.01.2000</time></aside>
          <article class="estu-content-panel"><div class="estu-content-copy">
          <h2>Örnek duyuru</h2><div class="estu-detail-meta">
          <time datetime="2026-10-15T15:09:09">15 Ekim 2026</time></div>
          <div class="estu-content-body"><p>Başvuru açıklaması.</p></div>
          </div></article></main>'''
        title, body, date = extract_detail(html, '.old-selector')
        self.assertEqual(title, 'Örnek duyuru')
        self.assertEqual(body, 'Başvuru açıklaması.')
        self.assertEqual(date, '15.10.2026')

    def test_legacy_design_still_works(self):
        site = load_sites_yaml()[0]
        html = '''<div class="gdlr-core-item-list"><h3 class="gdlr-core-blog-title">
          <a href="/tr/Duyuru/Detay/eski">Eski tasarım duyurusu</a></h3></div>'''
        items = extract_list_links(html, '', site['item_link_selector'], site['url'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], 'Eski tasarım duyurusu')
        title, body, date = extract_detail(
            '<div class="gdlr-core-single-blog-content"><h2>Eski başlık</h2>'
            '<p>Açıklama</p><time>14.10.2026</time></div>',
            site['detail_selector'],
        )
        self.assertEqual(title, 'Eski başlık')
        self.assertIn('Açıklama', body)
        self.assertEqual(date, '14.10.2026')


if __name__ == '__main__':
    unittest.main()

"""Test fixtures and sample data."""

SAMPLE_RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>MOHE Announcements</title>
    <link>https://www.mohe.gov.my/en/broadcast/announcements</link>
    <description>Ministry of Higher Education Malaysia Announcements</description>
    <language>en</language>
    <item>
      <title>New Higher Education Framework Announced</title>
      <link>https://www.mohe.gov.my/en/broadcast/announcements/article-001</link>
      <description>The Ministry announced the new framework for higher education planning.</description>
      <pubDate>Thu, 27 Feb 2026 10:00:00 GMT</pubDate>
      <guid>https://www.mohe.gov.my/en/broadcast/announcements/article-001</guid>
    </item>
    <item>
      <title>Scholarship Program Extended</title>
      <link>https://www.mohe.gov.my/en/broadcast/announcements/article-002</link>
      <description>The government scholarship program has been extended to more students.</description>
      <pubDate>Wed, 26 Feb 2026 15:30:00 GMT</pubDate>
      <guid>https://www.mohe.gov.my/en/broadcast/announcements/article-002</guid>
    </item>
  </channel>
</rss>
"""

SAMPLE_RSS_FEED_MS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>KPT Pengumuman</title>
    <link>https://www.mohe.gov.my/ms/broadcast/announcements</link>
    <description>Kementerian Pendidikan Tinggi Pengumuman</description>
    <language>ms</language>
    <item>
      <title>Kerangka Pendidikan Tinggi Baru Diumumkan</title>
      <link>https://www.mohe.gov.my/ms/broadcast/announcements/article-001</link>
      <description>Kementerian mengumumkan kerangka baru untuk perancangan pendidikan tinggi.</description>
      <pubDate>27 Februari 2026 10:00:00 GMT</pubDate>
      <guid>https://www.mohe.gov.my/ms/broadcast/announcements/article-001</guid>
    </item>
  </channel>
</rss>
"""

SAMPLE_HTML_LISTING = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>MOHE Announcements</title>
</head>
<body>
    <div class="listing-page">
        <table class="items-table">
            <tbody>
                <tr id="tr-1">
                    <td class="title-cell"><a href="/en/broadcast/announcements/item-1">First Announcement</a></td>
                    <td class="date-cell">27 February 2026</td>
                </tr>
                <tr id="tr-2">
                    <td class="title-cell"><a href="/en/broadcast/announcements/item-2">Second Announcement</a></td>
                    <td class="date-cell">26 February 2026</td>
                </tr>
            </tbody>
        </table>
        <nav class="pagination">
            <a rel="next" href="/en/broadcast/announcements?start=2">Next</a>
        </nav>
    </div>
</body>
</html>
"""

SAMPLE_DETAIL_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="description" content="Announcement detail page">
    <title>First Announcement - MOHE</title>
</head>
<body>
    <article>
        <h1>First Announcement</h1>
        <p class="meta">Published: 27 February 2026</p>
        <div class="content">
            <p>This is the full content of the first announcement from MOHE.</p>
            <p>It contains important information about higher education policies.</p>
        </div>
    </article>
</body>
</html>
"""

# DOCman HTML fixtures (staff downloads section)
SAMPLE_DOCMAN_HTML = """<!DOCTYPE html>
<html lang="ms">
<head><meta charset="UTF-8"><title>Arahan Pentadbiran - MOHE</title></head>
<body>
  <div class="k-component k-js-documents-list">
    <table class="k-js-documents-table">
      <thead>
        <tr>
          <th>Tajuk</th>
          <th>Tarikh</th>
          <th>Saiz</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <a href="/warga/muat-turun/pekeliling/arahan-pentadbiran/1715-arahan-pentadbiran-bil-1-2024/file">
              Arahan Pentadbiran Bil. 1 Tahun 2024
            </a>
          </td>
          <td>15 Januari 2024</td>
          <td>245 KB</td>
        </tr>
        <tr>
          <td>
            <a href="/warga/muat-turun/pekeliling/arahan-pentadbiran/1601-arahan-pentadbiran-bil-2-2023/file">
              Arahan Pentadbiran Bil. 2 Tahun 2023
            </a>
          </td>
          <td>20 Mac 2023</td>
          <td>189 KB</td>
        </tr>
        <tr>
          <td>
            <a href="/warga/muat-turun/pekeliling/arahan-pentadbiran/1600-arahan-pentadbiran-bil-1-2023/file">
              Arahan Pentadbiran Bil. 1 Tahun 2023
            </a>
          </td>
          <td>05 Februari 2023</td>
          <td>312 KB</td>
        </tr>
      </tbody>
    </table>
  </div>
</body>
</html>"""

SAMPLE_DOCMAN_HTML_EMPTY_TABLE = """<!DOCTYPE html>
<html lang="ms"><body>
  <table class="k-js-documents-table">
    <thead><tr><th>Tajuk</th><th>Tarikh</th></tr></thead>
    <tbody></tbody>
  </table>
</body></html>"""

SAMPLE_DOCMAN_HTML_NO_TABLE = """<!DOCTYPE html>
<html lang="ms"><body>
  <p>Tiada dokumen ditemui.</p>
</body></html>"""

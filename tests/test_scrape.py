from app.scrape import from_jsonld, html_to_text, linkedin_job_id, normalize_url

JSONLD_PAGE = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"Organization","name":"x"},
 {"@type":"JobPosting","title":"Senior Scrum Master","datePosted":"2026-10-29T00:00:00Z",
  "hiringOrganization":{"@type":"Organization","name":"Acme Bank"},
  "jobLocation":[{"@type":"Place","address":{"addressLocality":"Singapore","addressCountry":"SG"}}],
  "employmentType":["FULL_TIME"],
  "baseSalary":{"@type":"MonetaryAmount","currency":"SGD","value":{"minValue":9000,"maxValue":12000,"unitText":"MONTH"}},
  "description":"&lt;p&gt;Lead &lt;b&gt;three&lt;/b&gt; teams.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Scrum&lt;/li&gt;&lt;li&gt;Kanban&lt;/li&gt;&lt;/ul&gt;"}
]}
</script></head><body></body></html>"""


def test_jsonld_jobposting():
    d = from_jsonld(JSONLD_PAGE)
    assert d["title"] == "Senior Scrum Master"
    assert d["company"] == "Acme Bank"
    assert d["location"] == "Singapore, SG"
    assert d["salary"] == "SGD 9,000 – 12,000 per month"
    assert d["employment_type"] == "Full Time"
    assert d["posted_date"] == "2026-10-29"
    assert "Lead three teams." in d["description"]
    assert "- Scrum" in d["description"] and "- Kanban" in d["description"]


def test_jsonld_missing_returns_none():
    assert from_jsonld("<html><body>No data</body></html>") is None


def test_linkedin_ids_and_normalize():
    assert linkedin_job_id("https://www.linkedin.com/jobs/view/4012345678/?trk=abc") == "4012345678"
    assert linkedin_job_id("https://sg.linkedin.com/jobs/view/scrum-master-at-dbs-4012345678") == "4012345678"
    assert linkedin_job_id("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4012345678") == "4012345678"
    assert normalize_url("https://sg.linkedin.com/jobs/view/scrum-master-4012345678?refId=x") == \
        "https://www.linkedin.com/jobs/view/4012345678/"
    assert normalize_url("careers.acme.com/jobs/1?utm_source=li&id=7#apply") == "https://careers.acme.com/jobs/1?id=7"
    assert normalize_url("") == ""


def test_html_to_text():
    assert html_to_text("<p>One</p><p>Two<br>Three</p>") == "One\n\nTwo\nThree"

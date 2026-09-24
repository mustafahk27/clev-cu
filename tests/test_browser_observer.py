from clev.observe.browser import BrowserObserver, decode_elements

FORM = """
<header><nav aria-label="Main"><a href="/home">Home</a></nav></header>
<main>
  <h1>Checkout</h1>
  <div role="alert">Card declined</div>
  <form aria-label="Payment">
    <label for="email">Email address</label><input id="email" type="email" value="a@b.co">
    <label>Full name <input id="name"></label>
    <input id="search" type="search" placeholder="Search orders">
    <input id="pw" type="password" value="hunter2" aria-label="Password">
    <input id="cc" autocomplete="cc-number" value="4111111111111111" aria-label="Card">
    <input type="checkbox" id="terms" checked><label for="terms">Accept terms</label>
    <select aria-label="Country"><option>Oman</option><option selected>Pakistan</option></select>
    <span id="lbl">Place order now</span><button aria-labelledby="lbl">x</button>
    <input type="submit" value="Pay">
    <button disabled>Disabled one</button>
    <div role="button" aria-disabled="true">Fake disabled</div>
    <button style="display:none">Hidden one</button>
    <a href="/help"><img src="x.png" alt="Help"></a>
  </form>
</main>
<dialog open><h2>Confirm purchase</h2><button>OK</button></dialog>
"""


def by_name(obs, name):
    matches = [e for e in obs.elements if e.name == name]
    assert matches, f"no element named {name!r}: {[e.name for e in obs.elements]}"
    return matches[0]


async def test_roles_names_and_values(browser_session, open_page):
    await open_page(FORM, title="Checkout page")
    obs = await BrowserObserver(browser_session).observe()

    assert obs.app == "chromium"
    assert obs.title == "Checkout page"
    assert obs.url.endswith("/index.html")

    assert by_name(obs, "Email address").role == "textbox"
    assert by_name(obs, "Email address").value == "a@b.co"
    assert by_name(obs, "Full name").role == "textbox"  # wrapping <label>
    assert by_name(obs, "Search orders").role == "searchbox"  # placeholder fallback
    assert by_name(obs, "Accept terms").value == "checked"
    assert by_name(obs, "Country").role == "combobox"
    assert by_name(obs, "Country").value == "Pakistan"
    assert by_name(obs, "Place order now").role == "button"  # aria-labelledby
    assert by_name(obs, "Pay").role == "button"  # input[type=submit]
    assert by_name(obs, "Help").role == "link"  # name from image alt
    assert by_name(obs, "Checkout").role == "heading"
    assert by_name(obs, "Card declined").role == "alert"


async def test_secrets_are_redacted(browser_session, open_page):
    await open_page(FORM)
    obs = await BrowserObserver(browser_session).observe()
    assert by_name(obs, "Password").value == "[redacted]"
    assert by_name(obs, "Card").value == "[redacted]"
    dumped = obs.model_dump_json()
    assert "hunter2" not in dumped and "4111111111111111" not in dumped


async def test_enabled_and_visible_flags(browser_session, open_page):
    await open_page(FORM)
    obs = await BrowserObserver(browser_session).observe()
    assert by_name(obs, "Disabled one").enabled is False
    assert by_name(obs, "Fake disabled").enabled is False
    assert by_name(obs, "Pay").enabled is True
    assert by_name(obs, "Hidden one").visible is False
    assert by_name(obs, "Pay").visible is True
    assert by_name(obs, "Pay").bounds[2] > 0


async def test_context_paths(browser_session, open_page):
    await open_page(FORM)
    obs = await BrowserObserver(browser_session).observe()
    assert by_name(obs, "Home").context == 'banner > navigation "Main"'
    assert by_name(obs, "Pay").context == 'main > form "Payment"'
    assert by_name(obs, "OK").context == 'dialog "Confirm purchase"'


async def test_focused_element(browser_session, open_page):
    await open_page('<input aria-label="A"><input aria-label="B" autofocus>')
    await browser_session.page.focus("[aria-label=B]")
    obs = await BrowserObserver(browser_session).observe()
    assert [e.name for e in obs.elements if e.focused] == ["B"]


async def test_shadow_dom_elements_are_found(browser_session, open_page):
    await open_page(
        """<nav aria-label="Shadow nav"><div id="host"></div></nav>
        <script>
          const root = document.getElementById('host').attachShadow({mode: 'open'});
          root.innerHTML = '<button>Inside shadow</button>';
        </script>"""
    )
    obs = await BrowserObserver(browser_session).observe()
    assert by_name(obs, "Inside shadow").context == 'navigation "Shadow nav"'


async def test_ids_unique_and_max_elements(browser_session, open_page):
    await open_page("".join(f"<button>b{i}</button>" for i in range(30)))
    obs = await BrowserObserver(browser_session).observe()
    ids = [e.id for e in obs.elements]
    assert len(ids) == len(set(ids)) == 30
    capped = await BrowserObserver(browser_session, max_elements=10).observe()
    assert len(capped.elements) == 10


def test_decode_elements():
    payload = {
        "contexts": ["", "main"],
        "rows": [
            ["button", "Go", None, 1, 1 | 4, 1, 2, 3, 4],
            ["link", "Hidden", None, 0, 1 | 2, 0, 0, 0, 0],
        ],
    }
    a, b = decode_elements(payload)
    assert (a.id, a.context, a.enabled, a.focused, a.visible) == ("e0", "main", True, False, True)
    assert a.bounds == (1, 2, 3, 4)
    assert (b.id, b.focused, b.visible) == ("e1", True, False)

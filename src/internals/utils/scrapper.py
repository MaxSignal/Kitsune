import cloudscraper
from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry


def _get_connection(self, url, proxies=None):  # Monkeypatch.
    from requests.utils import select_proxy, prepend_scheme_if_needed
    from requests.exceptions import InvalidProxyURL
    from requests.compat import urlparse
    from urllib3.util import parse_url

    """Returns a urllib3 connection for the given URL. This should not be
    called from user code, and is only exposed for use when subclassing the
    :class:`HTTPAdapter <requests.adapters.HTTPAdapter>`.

    :param url: The URL to connect to.
    :param proxies: (optional) A Requests-style dictionary of proxies used on this request.
    :rtype: urllib3.ConnectionPool
    """
    proxy = select_proxy(url, proxies)

    if proxy:
        proxy = prepend_scheme_if_needed(proxy, 'http')
        proxy_url = parse_url(proxy)
        if not proxy_url.host:
            raise InvalidProxyURL("Please check proxy URL. It is malformed"
                                  " and could be missing the host.")
        proxy_manager = self.proxy_manager_for(proxy)
        # PATCH: Enable proxy headers
        if hasattr(proxy_manager, 'proxy_headers') and 'headers' in proxies:
            proxy_manager.proxy_headers.update(proxies.get('headers', {}))
        # ENDPATCH
        conn = proxy_manager.connection_from_url(url)
    else:
        # Only scheme should be lower case
        parsed = urlparse(url)
        url = parsed.geturl()
        conn = self.poolmanager.connection_from_url(url)

    return conn


def create_scrapper_session(
    useCloudscraper=True,
    retries=10,
    backoff_factor=0.3,
    status_forcelist=(500, 502, 504, 423)
):
    session = None
    if useCloudscraper:
        session = cloudscraper.create_scraper()
    else:
        session = Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    HTTPAdapter.get_connection = _get_connection
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

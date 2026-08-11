# ui/converters.py
"""URL converters for registry object names.

Repository names contain slashes, so the routes that carry one cannot use the
default `str` converter. Matching them with a bare `.+` -- which is what this
project did until now -- lets `..` through, and `requests` normalises `..` away
when it builds the request: a URL such as

    /ui/repositories/../../v2/_catalog/tag-details/

turns the outgoing call into `<registry>/artifactory/api/docker/v2/_catalog/...`,
outside the configured namespace, with the registry credentials attached. The
`tag-details` endpoint needs no authentication, so that was reachable by anyone
who could load the UI.

Constraining the pattern at the routing layer fixes it for every route at once,
and a name that does not match simply 404s.
"""


class RepositoryConverter:
    """Match a Docker repository name: slash-separated components.

    The distribution spec restricts components to
    `[a-z0-9]+((\\.|_|__|-+)[a-z0-9]+)*`. This is deliberately a little wider --
    uppercase and a leading digit are tolerated, since registries in the wild
    accept names Docker itself would not -- but every component must *start* with
    an alphanumeric character. That single requirement is what makes `.`, `..`
    and `.hidden` unmatchable, and percent-encodings are decoded before the
    pattern is applied, so `%2e%2e` does not slip past either.
    """

    regex = r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*"

    # The spec's limit on a full name. Enforced here rather than in the regex to
    # keep the pattern readable.
    max_length = 255

    def to_python(self, value):
        if len(value) > self.max_length:
            raise ValueError(f"repository name longer than {self.max_length} characters")
        return value

    def to_url(self, value):
        return value

"""A project for an answer-key run: a clone under HOME/code and the bare origin it pushes to.

The origin is a bare repository on disk, `<root>/remotes/<owner>/<name>.git`, so a run can
branch, push, fetch and land with no network, and ak reads `<owner>/<name>` off the origin's
path as it reads a GitHub slug off its URL.  `main` starts with one commit, `init`, holding an
empty `.keep` and the files given, pushed and tracked.  Git runs in the Home's environment, so
commits carry its placeholder name.

    from fixtures.akbin import Home
    from fixtures.gitrig import Rig
    with Home() as home:
        rig = Rig(home, "widgets", files={"AGENTS.md": "# widgets\\n"})
        rig.branch("fix-api", {"api.py": "x = 2\\n"})
        assert rig.branches() == ["fix-api", "main"]
"""


class Rig:
    def __init__(self, home, name="widgets", *, owner="acme", files=None):
        self.home, self.name, self.slug = home, name, f"{owner}/{name}"
        self.bare = home.root / "remotes" / owner / f"{name}.git"
        self.path = home.path / "code" / name
        self._git(home.path, "init", "-q", "--bare", "-b", "main", str(self.bare))
        self._git(home.path, "clone", "-q", str(self.bare), str(self.path))
        self.commit({".keep": "", **(files or {})}, "init", push=False)
        self.git("push", "-q", "-u", "origin", "main")

    def git(self, *args):
        """Run git in the clone; its output, stripped."""
        return self._git(self.path, *args)

    def origin(self, *args):
        """Run git in the bare origin; its output, stripped."""
        return self._git(self.bare, *args)

    def commit(self, files, message="change", *, push=True):
        """Write files (path -> text) in the clone and commit them on its branch, pushed
        unless told not to; the commit's sha."""
        for relative, text in files.items():
            path = self.path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        if push:
            self.git("push", "-q", "origin", "HEAD")
        return self.git("rev-parse", "HEAD")

    def branch(self, name, files=None, *, push=True):
        """A branch off the clone's main with files committed on it, pushed unless told not
        to; the clone is back on main after.  The branch's sha."""
        self.git("checkout", "-q", "-b", name, "main")
        try:
            return self.commit(files or {}, f"work on {name}", push=push)
        finally:
            self.git("checkout", "-q", "main")

    def head(self, ref="main", *, remote=True):
        """The sha a ref names in the origin, or in the clone when not `remote`; else None."""
        done = self.home.run("git", "-C", str(self.bare if remote else self.path),
                             "rev-parse", "-q", "--verify", f"{ref}^{{commit}}")
        return done.out.strip() if done.code == 0 else None

    def branches(self, *, remote=True):
        """The origin's branches, or the clone's own when not `remote`, sorted."""
        where = self.origin if remote else self.git
        return sorted(where("for-each-ref", "--format=%(refname:short)", "refs/heads").split())

    def files(self, ref="main", *, remote=True):
        """The paths a commit holds."""
        return (self.origin if remote else self.git)("ls-tree", "-r", "--name-only",
                                                      ref).split("\n")

    def _git(self, where, *args):
        done = self.home.run("git", "-C", str(where), *args)
        assert done.code == 0, f"git {' '.join(args)}: {done.err}"
        return done.out.strip()

package config

import "testing"

func TestSyntax(t *testing.T) {
	for _, valid := range []string{
		"", "# config\n", "max_runs = 0\n",
		"[defaults]\norchestrator = 'acme'\nworkers = [\"acme\", # selected\n 'other',]\n",
		"[models.\"acme.pro\"]\neffort = 'high'\n",
		"x = {one = 1, two = [true, false]}\n",
		"x = '''many\nlines'''\n", "x = \"\"\"many\\\n  lines\"\"\"\n",
		"x = 1979-05-27T07:32:00Z\ny = 1979-05-27 07:32:00\n",
		"x = 0001-01-01t00:00:00.999999999z\ny = 2000-02-29T23:59:59-23:59\nz = [07:32:00.5, 1979-05-27]\n",
		"x = 0xCA_FE\ny = -1_000.2e+4\nz = +inf\n",
		"[[models.acme.accounts]]\nname='one'\n[[models.acme.accounts]]\nname='two'\n",
		"[a.b]\nx=1\n[a]\ny=2\n",
		"a.b.c=1\na.b.d=2\n", "[a]\nb.c=1\nb.d=2\n",
		"[a.b]\nx=1\n[a.c]\ny=2\n", "[[a]]\nx=1\n[a.b]\ny=2\n",
	} {
		if err := TOML(valid); err != nil {
			t.Errorf("valid TOML %q: %v", valid, err)
		}
	}
	for _, invalid := range []string{
		"garbage = = =\n", "x =", "x = nope", "x = 01", "x = [1,", "x = {one = 1,}",
		"[models\nx = 1", "x = 'unterminated", "x = \"bad\\x41\"", "x = \"\\uD800\"",
		"x = 'one\ntwo'", "x = 1 y = 2", "x = 1\x00", "x = 1\r", "x = \"\"\"bad\\  text\"\"\"",
		"max_runs=1\nmax_runs=2\n", "[models.acme]\nx=1\n[models.acme]\ny=2\n",
		"a.b=1\na.b=2\n", "x={a=1}\nx.b=2\n", "x={a=1,a=2}\n", "x=1\n[x]\ny=2\n",
		"[a.b]\nx=1\n[a]\nb.c=2\n", "[a.b]\nx=1\n[a]\nb.c.d=2\n",
		"[[a.b]]\nx=1\n[a]\nb.c=2\n",
		"x = 1\u00a0\n", "x = \u00a01\n", "x = true\u0085\n", "x = 0000-01-01\n", "x = 1979-02-29\n",
		"x = 1979-05-27T07:32:00+24:00\n", "x = 1979-05-27T07:32:00+00:60\n", "x = 1979-05-27T7:32:00Z\n",
		"x = 7:32:00\n", "x = 07:32:00Z\n",
	} {
		if err := TOML(invalid); err == nil {
			t.Errorf("accepted invalid TOML %q", invalid)
		}
	}
}

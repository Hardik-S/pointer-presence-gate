# Pointer Presence Gate

An offline command-line check for whether each synthetic JSONL record contains a set of required JSON values at RFC 6901 JSON Pointer locations. It checks **presence**: `null`, `false`, `0`, and empty values all count as present. It does not validate a full JSON Schema or judge whether data is correct or safe.

## Install and run

Requires Python 3.10 or newer. From a wheel or source distribution installed in your environment:

```console
python -m pip install pointer-presence-gate
pointer-presence-gate POLICY.json ROWS.jsonl
```

For this repository, build and install the local project with an explicit PEP 517 backend:

```console
python -m pip install .
pointer-presence-gate examples/policy.json examples/rows.jsonl
```

The tool reads both files and prints one compact JSON result to stdout. It never prints input values, IDs, pointers, paths, or parser errors. It does not write files, access the network, or launch a model.

Exit codes are `0` when every row contains every required pointer, `1` when one or more rows are missing at least one required pointer, and `2` when arguments or either input are invalid. Results have one of these shapes:

```json
{"status":"valid","record_count":2,"missing_lines":[]}
{"status":"missing_required","record_count":2,"missing_lines":[2]}
{"status":"invalid_input"}
```

`missing_lines` uses sorted, one-based physical JSONL row numbers; each affected row appears once. Empty rows files are valid. `-h` and `--help` print usage and exit successfully.

## Input contract

The policy is one UTF-8 JSON document with exactly one property:

```json
{"required":["/account/id","/preferences/email"]}
```

`required` contains zero to 1,000 unique JSON Pointer **strings** of at most 4,096 Unicode code points. The empty string selects the payload root. Other pointers start with `/`; each tilde must be `~0` or `~1`. Tokens are decoded in that order, with no Unicode normalization. URI-fragment pointer notation beginning with `#` is not accepted.

Each nonblank JSONL row has exactly an `id` and a `payload` property. IDs are nonempty unique strings. Pointer resolution starts at `payload`, never at the row wrapper. Object properties match exact keys, including empty, slash, tilde, and numeric-looking keys. Array indices use ASCII `0` or a nonzero digit followed by ASCII digits, with no leading zero. Invalid array tokens, out-of-range indexes, and traversal through a scalar are unresolved. A missing pointer is a presence result; malformed input is an invalid-input result.

Both inputs are fully validated before a result is produced. UTF-8 must be strict; duplicate JSON object keys, non-finite numbers, lone surrogates, duplicate IDs, blank rows, extra/missing properties, malformed pointers, and container nesting deeper than 128 are rejected. JSONL rows are delimited only by CR, LF, or CRLF; one final terminator is allowed. Ordinary finite JSON numbers are accepted without binary-float overflow. The implementation uses only the Python standard library at runtime.

## Scope

This is a narrow application of the established RFC 6901 string representation and resolution rules. It is not a JSON Schema validator, provider compatibility checker, content-quality or safety validator, patch editor, or novelty claim. Use synthetic test data; the output establishes only whether a location resolves in each supplied payload.

## Development

Run the standard-library tests without installing anything:

```console
python -m unittest discover -s tests -v
```

The CI acceptance script also builds a wheel, installs it into a fresh non-editable virtual environment, checks the installed console script and import/version, and exercises exit codes, help, output privacy, and the quickstart example.

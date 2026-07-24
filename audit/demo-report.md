# AI-SDLC Repo Audit Report

**Repository:** https://github.com/jagmstar/letta-features-company  
**Clone source:** https://github.com/jagmstar/letta-features-company  
**Commit:** e782db79c62746c382780fa5560a8f8e97d77e56  
**Branch:** main  
**Generated:** 2026-07-24T13:56:12+00:00  
**Overall score:** 50.80 / 100  
**Risk level:** elevated

## Executive summary

Overall score: **50.80/100** (elevated risk). The strongest signals are license compliance scored 0.0; test coverage scored 2.3; security scored 45.0.

## Scorecard

| Check | Score | Key metric |
| --- | ---: | --- |
| Code quality | 50.41 | 344 functions; complexity max 23 |
| Test coverage | 2.30 | 2.3% coverage; 15 test files |
| Security | 45.00 | 7 secret-like hits |
| Documentation | 77.92 | 14.81% module docstrings |
| CI/CD | 100.00 | 2 workflow files; 1 test jobs |
| Dependency health | 80.00 | 0 manifest(s); 2 external imports |
| License compliance | 0.00 | 0 license file(s) |

## Code quality

### Metrics
| Metric | Value |
| --- | ---: |
| Python Files | `27` |
| Source Lines | `4943` |
| Comment Lines | `13` |
| Comment Density Percent | `0.26` |
| Module Docstring Coverage Percent | `14.81` |
| Function Count | `344` |
| Avg Function Length | `13.46` |
| Max Function Length | `357` |
| Max Cyclomatic Complexity | `23` |
| Functions Over 80 Lines | `1` |
| Functions Over Complexity 10 | `3` |
| Todo Fixme Hits | `7` |
| Files With Classes | `13` |
| Largest Python File Lines | `1082` |
| Longest Function | `{"file": "dashboard/generate_dashboard.py", "name": "build_html", "lineno": 216, "end_lineno": 572, "length": 357}` |

### Findings
- **Medium** — Module docstring coverage is light: Only 4 of 27 Python files include module docstrings.
- **Medium** — At least one function is relatively complex: Maximum observed cyclomatic complexity is 23.
- **Medium** — Some functions are long enough to review: 1 functions exceed 80 lines.
- **Low** — TODO/FIXME markers remain in source: Found 7 TODO/FIXME-style markers across Python files.

## Test coverage

### Metrics
| Metric | Value |
| --- | ---: |
| Test Files | `15` |
| Test Cases | `127` |
| Source Files | `12` |
| Coverage Percent | `2.3` |
| Test Run Status | `"passed"` |
| Test Runner | `"pytest"` |
| Test Command | `"C:\\Users\\jagm\\AppData\\Local\\Programs\\Python\\Python312\\python.exe -m coverage run -m pytest -q"` |
| Measured Source Files | `2` |
| Unmeasured Source Files | `10` |
| Unmeasured Files | `["api/schedules_api.py", "channels/channels_manager.py", "channels/__init__.py", "dashboard/generate_dashboard.py", "imagegen/image_manager.py", "monitoring/health_monitor.py", "skills/example_skill.py", "skills/skills_manager.py", "skills/__init__.py", "storage/db.py"]` |
| Covered Lines | `68` |
| Source Lines | `2961` |
| Coverage Json Totals | `{"covered_lines": 2659, "num_statements": 3200, "percent_covered": 83.09375, "percent_covered_display": "83", "missing_lines": 541, "excluded_lines": 43, "percent_statements_covered": 83.09375, "percent_statements_covered_display": "83"}` |

### Findings
- **Medium** — Test coverage is below target: Measured coverage is 2.3%.

## Security issues

### Metrics
| Metric | Value |
| --- | ---: |
| Secret Like Hits | `7` |
| Shell True Hits | `2` |
| Unsafe Load Hits | `0` |
| Dynamic Exec Hits | `1` |
| Top Files | `[["production_scheduler.py", 1], ["docs/API-REFERENCE.md", 1], ["tests/test_docs_accuracy.py", 1], ["tests/test_integration.py", 1], ["api/tests/test_channels_api.py", 1], ["api/tests/test_images_api.py", 1], ["api/tests/test_schedules_api.py", 1]]` |

### Findings
- **High** — Secret-like values found in repository text: Detected 7 potential secret patterns in tracked files.
- **Medium** — Shell invocation detected in code: Found 2 shell=True or shell-like invocation(s).
- **Medium** — Dynamic code execution primitives are present: Detected 1 eval/exec/compile call(s).

## Documentation

### Metrics
| Metric | Value |
| --- | ---: |
| Docs Files | `23` |
| Markdown Files | `23` |
| Module Docstring Coverage Percent | `14.81` |
| Docs Ratio Percent | `40.35` |
| Readme Present | `true` |
| Openapi Present | `true` |
| Total Python Files | `27` |
| Module Docstrings | `4` |

### Findings
- **Low** — Python module docstring coverage can improve: Only 4 of 27 Python files have module docstrings.

## CI/CD

### Metrics
| Metric | Value |
| --- | ---: |
| Workflow Files | `2` |
| Job Count | `6` |
| Test Job Count | `1` |
| Deploy Workflows | `1` |
| Artifact Uploads | `2` |
| Build Commands | `3` |
| Workflow Triggers | `2` |

### Findings
- **Info** — No major issues detected: Nothing material stood out in this check.

## Dependency health

### Metrics
| Metric | Value |
| --- | ---: |
| Manifest Files | `0` |
| Manifest Types | `{}` |
| Declared Dependencies | `0` |
| Pinned Dependencies | `0` |
| External Imports | `["psutil", "pytest"]` |
| External Import Count | `2` |
| Lockfiles | `0` |
| Lockfile Names | `[]` |
| Import Sources | `{"psutil": 3, "pytest": 6}` |

### Findings
- **Medium** — No dependency manifest detected: The repository does not declare dependencies in a recognized manifest file.
- **Medium** — Third-party imports are present without a manifest: Detected 2 external import(s) such as psutil, pytest.

## License compliance

### Metrics
| Metric | Value |
| --- | ---: |
| License Files | `0` |
| License Names | `[]` |
| Detected License | `null` |
| License Present | `false` |

### Findings
- **High** — No license file found: The repository does not include a LICENSE or COPYING file.

## Recommended next steps

1. Review high-severity findings first.
2. Decide whether to fix, document, or accept each risk.
3. Re-run the audit after remediation to compare scores.

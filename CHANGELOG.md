Changelog for toa5-merge
========================

0.3.0 - Sat, Aug 22 2026
------------------------

- Data fields containing double quotes or line breaks are now rejected while loading
- Reduced database size by parsing raw CSV rows on demand instead of storing a second JSON representation

0.2.0 - Fri, Aug 21 2026
------------------------

`commit 576c892f755135bd85cf358ab25e9289f197e90e`

- CSV output customized so that generated files are closer to TOA5 "standard"
- Identical rows with identical column headers are now recognized when their environment lines differ
- Improved rollback behavior when reading a file is interrupted or fails
- Correction CLI option help messages

0.1.0 - Sun, Nov 23 2025
------------------------

`commit 6375481d1df7b13913f6695e8eac6d57be953f78`

- Initial public release

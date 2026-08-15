# Documentation scope and code alignment

Target branch: `release/2.3.0b1-stabilization`

Target package version: `2.3.0b1`

The documentation describes only public code and verified behavior in this
branch. Planned commands such as the final `plyctl setup`, source manager,
patch manager, and complete resource-aware build interface are explicitly
labelled as roadmap items.

The release-critical documentation covers:

- product principles and Core boundaries;
- workspace and operations behavior;
- local Python node loading;
- portable deployment and architecture restrictions;
- ROS 2 and FAST-LIVO2 reference integration;
- semantic-mapping qualification state;
- current release notes and stabilization backlog.

Validation:

- Python syntax checks;
- release-metadata consistency tests;
- release-critical local-link checks;
- English and Russian Sphinx builds with `-W --keep-going` when Sphinx is
  installed;
- GitHub Actions remains the authoritative full documentation build.

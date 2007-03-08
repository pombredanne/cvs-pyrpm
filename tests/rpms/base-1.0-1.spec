Summary: base
Name: base
Version: 1.0
Release: 1
License: GPL
Group: System Environment/Base
URL: http:://none.none/
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root
Provides: /bin/base
Requires: base-common = %{version}-%{release}
Requires: setup

%description
base package

%package common
Summary: common base files
Group: System Environment/Base
Conflicts: base < 1.0
Requires: base = %{version}-%{release}
Provides: /usr/share/base/base

%description common
common base package

%prep

%install
rm -rf $RPM_BUILD_ROOT

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)

%files common
%defattr(-,root,root,-)

%changelog
* Sun Jun 18 2006 Thomas Woerner <twoerner@redhat.com> - 1.0-1
- Initial build.


Summary: setup
Name: setup
Version: 1.0
Release: 1
License: GPL
Group: System Environment/Base
URL: http://none.none/
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-root
Requires: filesys

%description
setup

%prep

%build

%install
rm -rf $RPM_BUILD_ROOT

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root,-)

%changelog
* Mon Jun 19 2006 Thomas Woerner <twoerner@redhat.com> - 1.0-1
- Initial build.


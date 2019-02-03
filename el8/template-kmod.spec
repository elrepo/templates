# Define the kmod package name here.
%define kmod_name		PHOO

# If kmod_kernel_version isn't defined on the rpmbuild line, define it here.
%{!?kmod_kernel_version: %define kmod_kernel_version 4.18.0-32.el8}

%{!?dist: %define dist .el8}

Name:		kmod-%{kmod_name}
Version:	0.0
Release:	1%{?dist}
Summary:	%{kmod_name} kernel module(s)
Group:		System Environment/Kernel
License:	GPLv2
URL:		http://www.kernel.org/

# Sources
Source0:	%{kmod_name}-%{version}.tar.gz
Source5:	GPL-v2.0.txt

# Source code patches

%define findpat %( echo "%""P" )
%define __find_requires /usr/lib/rpm/redhat/find-requires.ksyms
%define __find_provides /usr/lib/rpm/redhat/find-provides.ksyms %{kmod_name} %{?epoch:%{epoch}:}%{version}-%{release}
%define dup_state_dir %{_localstatedir}/lib/rpm-state/kmod-dups
%define kver_state_dir %{dup_state_dir}/kver
%define kver_state_file %{kver_state_dir}/%{kmod_kernel_version}.%{arch}
%define dup_module_list %{dup_state_dir}/rpm-kmod-%{kmod_name}-modules

BuildRoot:	%(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)
BuildRequires:	kernel-devel = %{kmod_kernel_version} redhat-rpm-config kernel-abi-whitelists
ExclusiveArch:	x86_64
%global kernel_source() %{_usrsrc}/kernels/%{kmod_kernel_version}.%{arch}

%global _use_internal_dependency_generator 0
Provides:	kernel-modules = %{kmod_kernel_version}.%{_target_cpu}
Provides:	kmod-%{kmod_name} = %{?epoch:%{epoch}:}%{version}-%{release}
Requires(post):	%{_sbindir}/weak-modules
Requires(postun):	%{_sbindir}/weak-modules
Requires:	kernel >= %{kmod_kernel_version}

# if there are multiple kmods for the same driver from different vendors,
# they should conflict with each other.
## Conflicts:	kmod-%{kmod_name}

%description
This package provides the %{kmod_name} kernel module(s).
It is built to depend upon the specific ABI provided by a range of releases
of the same variant of the Linux kernel and not on any one specific build.

%prep
%setup -n %{kmod_name}-%{version}

# Apply patch(es)
# % patch0 -p1

%build
%{__make} -C %{kernel_source} V=1 M=$PWD \
EXTRA_CFLAGS="-mindirect-branch=thunk-inline -mindirect-branch-register" \
%{nil}

# mark modules executable so that strip-to-file can strip them
find . -name "*.ko" -type f -exec chmod u+x '{}' +

whitelist="/lib/modules/kabi-current/kabi_whitelist_%{_target_cpu}"
for modules in $( find . -name "*.ko" -type f -printf "%{findpat}\n" | sed 's|\.ko$||' | sort -u ) ; do
	# update depmod.conf
	module_weak_path=$(echo $modules | sed 's/[\/]*[^\/]*$//')
	if [ -z "$module_weak_path" ]; then
		module_weak_path=%{name}
	else
		module_weak_path=%{name}/$module_weak_path
	fi
	echo "override $(echo $modules | sed 's/.*\///') $(echo %{kmod_kernel_version} | sed 's/\.[^\.]*$//').* weak-updates/$module_weak_path" >> depmod.conf

# update greylist
nm -u ./$modules.ko | sed 's/.*U //' |  sed 's/^\.//' | sort -u | while read -r symbol; do
		grep -q "^\s*$symbol\$" $whitelist || echo "$symbol" >> ./greylist
	done
done
sort -u greylist | uniq > greylist.txt

%install
export INSTALL_MOD_PATH=$RPM_BUILD_ROOT
export INSTALL_MOD_DIR=extra/%{name}
%{__make} -C %{kernel_source} modules_install \
	M=$PWD
# Cleanup unnecessary kernel-generated module dependency files.
find $INSTALL_MOD_PATH/lib/modules -iname 'modules.*' -exec rm {} \;

%{__install} -m 644 -D depmod.conf $RPM_BUILD_ROOT/etc/depmod.d/kmod-${kmod_name}.conf
%{__install} -m 644 -D greylist.txt $RPM_BUILD_ROOT/usr/share/doc/kmod-%{kmod_name}/greylist.txt

%clean
rm -rf $RPM_BUILD_ROOT

%post
modules=( $(find /lib/modules/%{kmod_kernel_version}.x86_64/extra/kmod-%{kmod_name} | grep '\.ko$') )
printf '%s\n' "${modules[@]}" | %{_sbindir}/weak-modules --add-modules --no-initramfs

mkdir -p "%{kver_state_dir}"
touch "%{kver_state_file}"

exit 0

%posttrans
# We have to re-implement part of weak-modules here because it doesn't allow
# calling initramfs regeneration separately
if [ -f "%{kver_state_file}" ]; then
	kver_base="%{kmod_kernel_version}"
	kvers=$(ls -d "/lib/modules/${kver_base%%.*}"*)

	for k_dir in $kvers; do
		k="${k_dir#/lib/modules/}"

		tmp_initramfs="/boot/initramfs-$k.tmp"
		dst_initramfs="/boot/initramfs-$k.img"

		# The same check as in weak-modules: we assume that the kernel present
		# if the symvers file exists.
		if [ -e "/boot/symvers-$k.gz" ]; then
			/usr/bin/dracut -f "$tmp_initramfs" "$k" || exit 1
			cmp -s "$tmp_initramfs" "$dst_initramfs"
			if [ "$?" = 1 ]; then
				mv "$tmp_initramfs" "$dst_initramfs"
			else
				rm -f "$tmp_initramfs"
			fi
		fi
	done

	rm -f "%{kver_state_file}"
	rmdir "%{kver_state_dir}" 2> /dev/null
fi

rmdir "%{dup_state_dir}" 2> /dev/null

exit 0

%preun
if rpm -q --filetriggers kmod 2> /dev/null| grep -q "Trigger for weak-modules call on kmod removal"; then
	mkdir -p "%{kver_state_dir}"
	touch "%{kver_state_file}"
fi

mkdir -p "%{dup_state_dir}"
rpm -ql kmod-%{kmod_name}-%{version}-%{release}.%{arch} | grep '\.ko$' > "%{dup_module_list}"

%postun
if rpm -q --filetriggers kmod 2> /dev/null| grep -q "Trigger for weak-modules call on kmod removal"; then
	initramfs_opt="--no-initramfs"
else
	initramfs_opt=""
fi

modules=( $(cat "%{dup_module_list}") )
rm -f "%{dup_module_list}"
printf '%s\n' "${modules[@]}" | %{_sbindir}/weak-modules --remove-modules $initramfs_opt

rmdir "%{dup_state_dir}" 2> /dev/null

exit 0

%files
%defattr(644,root,root,755)
/lib/modules/%{kmod_kernel_version}.%{arch}/
config /etc/depmod.d/kmod-%{kmod_name}.conf
%doc /usr/share/doc/kmod-%{kmod_name}-%{version}/

%changelog
* Fri Feb 01 2019 Akemi Yagi <toracat@elrepo.org> 0.0-1
- Initial el8 build of the kmod package.

import json
from tempfile import NamedTemporaryFile

import pytest
import yaml
from jsonschema import validate

from Pegasus.api.errors import DuplicateError
from Pegasus.api.mixins import EventType, Namespace
from Pegasus.api.site_catalog import OS, Arch
from Pegasus.api.transformation_catalog import (
    PEGASUS_VERSION,
    Container,
    Transformation,
    TransformationCatalog,
    TransformationSite,
)
from Pegasus.api.writable import _CustomEncoder


class TestTransformationSite:
    @pytest.mark.parametrize(
        "name, pfn, transformation_type, kwargs",
        [
            (
                "local",
                "/pfn",
                True,
                {
                    "arch": Arch.X86_64,
                    "os_type": None,
                    "os_release": None,
                    "os_version": None,
                    "glibc": None,
                    "container": None,
                },
            ),
            (
                "local",
                "/pfn",
                True,
                {
                    "arch": Arch.X86_64,
                    "os_type": None,
                    "os_release": None,
                    "os_version": None,
                    "glibc": None,
                    "container": None,
                },
            ),
            (
                "local",
                "/pfn",
                True,
                {
                    "arch": Arch.X86_64,
                    "os_type": OS.LINUX,
                    "os_release": None,
                    "os_version": None,
                    "glibc": None,
                    "container": None,
                },
            ),
            (
                "local",
                "/pfn",
                True,
                {
                    "arch": Arch.X86_64,
                    "os_type": OS.LINUX,
                    "os_release": "release",
                    "os_version": "1.1.1",
                    "glibc": "123",
                    "container": "centos-pegasus",
                },
            ),
        ],
    )
    def test_valid_transformation_site(
        self, name: str, pfn: str, transformation_type: bool, kwargs: dict
    ):
        assert TransformationSite(name, pfn, transformation_type, **kwargs)

    @pytest.mark.parametrize(
        "name, pfn, transformation_type, kwargs",
        [
            (
                "local",
                "/pfn",
                True,
                {
                    "arch": "should be one of Arch",
                    "os_type": None,
                    "os_release": None,
                    "os_version": None,
                    "glibc": None,
                    "container": None,
                },
            ),
            (
                "local",
                "/pfn",
                True,
                {
                    "arch": Arch.X86_64,
                    "os_type": "should be one of OS",
                    "os_release": None,
                    "os_version": None,
                    "glibc": None,
                    "container": None,
                },
            ),
        ],
    )
    def test_invalid_transformation_site(
        self, name: str, pfn: str, transformation_type: bool, kwargs: dict
    ):
        with pytest.raises(TypeError) as e:
            TransformationSite(name, pfn, transformation_type, **kwargs)

        assert "invalid" in str(e)

    @pytest.mark.parametrize(
        "transformation_site, expected_json",
        [
            (
                TransformationSite("local", "/pfn", True),
                {"name": "local", "pfn": "/pfn", "type": "stageable"},
            ),
            (
                TransformationSite(
                    "local",
                    "/pfn",
                    False,
                    arch=Arch.X86_64,
                    os_type=OS.LINUX,
                    os_release="release",
                    os_version="1.1.1",
                    glibc="123",
                    container="centos-pegasus",
                ),
                {
                    "name": "local",
                    "pfn": "/pfn",
                    "type": "installed",
                    "arch": "x86_64",
                    "os.type": "linux",
                    "os.release": "release",
                    "os.version": "1.1.1",
                    "glibc": "123",
                    "container": "centos-pegasus",
                },
            ),
        ],
    )
    def test_tojson_no_profiles_or_metadata(
        self,
        transformation_site: TransformationSite,
        expected_json: dict,
        convert_yaml_schemas_to_json,
        load_schema,
    ):
        result = transformation_site.__json__()

        transformation_site_schema = load_schema("tc-5.0.json")["$defs"][
            "transformation"
        ]["properties"]["sites"]["items"]

        validate(instance=result, schema=transformation_site_schema)

        assert transformation_site.__json__() == expected_json

    def test_tojson_with_profiles_and_metadata(
        self, convert_yaml_schemas_to_json, load_schema
    ):
        t = (
            TransformationSite("local", "/pfn", False)
            .add_env(JAVA_HOME="/java/home")
            .add_metadata(key="value")
        )

        result = t.__json__()
        expected = {
            "name": "local",
            "pfn": "/pfn",
            "type": "installed",
            "profiles": {Namespace.ENV.value: {"JAVA_HOME": "/java/home"}},
            "metadata": {"key": "value"},
        }

        transformation_site_schema = load_schema("tc-5.0.json")["$defs"][
            "transformation"
        ]["properties"]["sites"]["items"]

        validate(instance=result, schema=transformation_site_schema)

        assert result == expected


class TestTransformation:
    def test_add_single_tranformation_site_constructor(self):
        t1 = Transformation("t1")
        assert len(t1.sites) == 0

        # pfn, and is_stageable is not provided, TransformationSite should not be added
        t2 = Transformation("t2", site="local")
        assert len(t2.sites) == 0

        # is_stageable is not provided, TransformationSite should not be added
        t3 = Transformation("t3", site="local", pfn="/t3")
        assert len(t3.sites) == 0

        # site, pfn, is_stageable provided, TransformationSite should be added
        t4 = Transformation("t4", site="local", pfn="/t4", is_stageable=False)
        assert len(t4.sites) == 1

    @pytest.mark.parametrize(
        "transformation",
        [
            (Transformation("name")),
            (Transformation("name", namespace="namespace")),
            (Transformation("name", namespace="namespace", version="1.1")),
        ],
    )
    def test_get_key(self, transformation):
        assert transformation._get_key() == "{}::{}::{}".format(
            transformation.namespace, transformation.name, transformation.version
        )

    def test_hash(self):
        assert hash(Transformation("name")) == hash("None::name::None")

    @pytest.mark.parametrize(
        "t1, t2, is_eq",
        [
            (Transformation("name"), Transformation("name"), True),
            (
                Transformation("name", namespace="namespace"),
                Transformation("name"),
                False,
            ),
        ],
    )
    def test_eq(self, t1, t2, is_eq):
        assert (t1 == t2) == is_eq

    def test_eq_invalid(self):
        with pytest.raises(ValueError) as e:
            Transformation("name") == "tr"

        assert "Transformation cannot be compared with" in str(e)

    def test_add_site(self):
        t = Transformation("test")
        t.add_sites(TransformationSite("local", "/pfn", True))
        assert "local" in t.sites

    def test_add_duplicate_site(self):
        with pytest.raises(DuplicateError) as e:
            t = Transformation("test")
            t.add_sites(TransformationSite("local", "/pfn", True))
            t.add_sites(TransformationSite("isi", "/pfn", True))

            t.add_sites(TransformationSite("local", "/pfn", True))

        assert "local" in str(e)

    def test_add_invalid_site(self):
        with pytest.raises(TypeError) as e:
            t = Transformation("test")
            t.add_sites("badsite")

        assert "badsite" in str(e)

    def test_add_requirement_as_str(self):
        t = Transformation("test")
        required_transformation_name = "required"
        t.add_requirement(required_transformation_name)

        assert "None::required::None" in t.requires

    def test_add_requirement_as_transformation_object(self):
        t = Transformation("test")
        required = Transformation("required", namespace=None, version=None)

        t.add_requirement(required)
        assert required._get_key() in t.requires

    def test_add_invalid_requirement(self):
        t = Transformation("test")
        with pytest.raises(TypeError) as e:
            t.add_requirement(1)

        assert "invalid required_transformation: {tr}".format(tr=1) in str(e)

    def test_add_duplicate_requirement_as_str(self):
        t = Transformation("test")
        required = "required"

        t.add_requirement(required)
        with pytest.raises(DuplicateError) as e:
            t.add_requirement(required)

        assert "transformation: None::required::None" in str(e)

    def test_add_duplicate_requirement_as_transformation_object(self):
        t = Transformation("test")
        required = Transformation("required", namespace=None, version=None)

        t.add_requirement(required)
        with pytest.raises(DuplicateError) as e:
            t.add_requirement(required)

        assert "transformation: None::required::None" in str(e)

    def test_chaining(self):
        t = (
            Transformation("test")
            .add_sites(
                TransformationSite("local", "/pfn", True).add_env(
                    JAVA_HOME="/java/home"
                )
            )
            .add_requirement("required")
        )

        assert "local" in t.sites
        assert t.sites["local"].profiles["env"]["JAVA_HOME"] == "/java/home"
        assert "None::required::None" in t.requires

    def test_tojson_without_profiles_hooks_metadata(
        self, convert_yaml_schemas_to_json, load_schema
    ):
        t = Transformation("test", namespace="pegasus")
        t.add_sites(TransformationSite("local", "/pfn", True))
        t.add_requirement("required")

        result = json.loads(json.dumps(t, cls=_CustomEncoder))
        expected = {
            "name": "test",
            "namespace": "pegasus",
            "requires": ["None::required::None"],
            "sites": [{"name": "local", "pfn": "/pfn", "type": "stageable"}],
        }

        transformation_schema = load_schema("tc-5.0.json")["$defs"]["transformation"]

        validate(instance=result, schema=transformation_schema)

        assert result == expected

    def test_tojson_with_profiles_hooks_metadata(
        self, convert_yaml_schemas_to_json, load_schema
    ):
        t = Transformation("test", namespace="pegasus")
        t.add_sites(
            TransformationSite("local", "/pfn", True).add_env(JAVA_HOME="/java/home")
        )
        t.add_requirement("required")

        t.add_env(JAVA_HOME="/java/home")
        t.add_shell_hook(EventType.START, "/bin/echo hi")
        t.add_metadata(key="value")

        result = json.loads(json.dumps(t, cls=_CustomEncoder))
        expected = {
            "name": "test",
            "namespace": "pegasus",
            "requires": ["None::required::None"],
            "sites": [
                {
                    "name": "local",
                    "pfn": "/pfn",
                    "type": "stageable",
                    "profiles": {"env": {"JAVA_HOME": "/java/home"}},
                }
            ],
            "metadata": {"key": "value"},
            "profiles": {Namespace.ENV.value: {"JAVA_HOME": "/java/home"}},
            "hooks": {"shell": [{"_on": EventType.START.value, "cmd": "/bin/echo hi"}]},
        }

        transformation_schema = load_schema("tc-5.0.json")["$defs"]["transformation"]
        validate(instance=result, schema=transformation_schema)

        assert result == expected


class TestContainer:
    def test_valid_container(self):
        assert Container("test", Container.DOCKER, "image", ["mount"])

    def test_invalid_container(self):
        with pytest.raises(TypeError) as e:
            Container("test", "container_type", "image", ["mount"])

        assert "invalid container_type: container_type" in str(e)

    def test_tojson_no_profiles(self, convert_yaml_schemas_to_json, load_schema):
        c = Container("test", Container.DOCKER, "image", ["mount"])

        result = c.__json__()
        expected = {
            "name": "test",
            "type": Container.DOCKER.value,
            "image": "image",
            "mounts": ["mount"],
        }

        container_schema = load_schema("tc-5.0.json")["$defs"]["container"]
        validate(instance=result, schema=container_schema)

        assert result == expected

    def test_tojson_with_profiles(self, convert_yaml_schemas_to_json, load_schema):
        c = Container("test", Container.DOCKER, "image", ["mount"])
        c.add_env(JAVA_HOME="/java/home")

        result = c.__json__()
        expected = {
            "name": "test",
            "type": Container.DOCKER.value,
            "image": "image",
            "mounts": ["mount"],
            "profiles": {Namespace.ENV.value: {"JAVA_HOME": "/java/home"}},
        }

        container_schema = load_schema("tc-5.0.json")["$defs"]["container"]
        validate(instance=result, schema=container_schema)

        assert result == expected


class TestTransformationCatalog:
    def test_add_single_transformation(self):
        tc = TransformationCatalog()
        tc.add_transformations(Transformation("test"))

        assert "None::test::None" in tc.transformations
        assert len(tc.transformations) == 1

    def test_add_multiple_transformations(self):
        tc = TransformationCatalog()

        t1 = Transformation("name")
        t2 = Transformation("name", namespace="namespace")
        t3 = Transformation("name", namespace="namespace", version="version")

        tc.add_transformations(t1, t2, t3)

        assert "None::name::None" in tc.transformations
        assert "namespace::name::None" in tc.transformations
        assert "namespace::name::version" in tc.transformations
        assert len(tc.transformations) == 3

    def test_add_duplicate_transformation(self):
        tc = TransformationCatalog()
        tc.add_transformations(Transformation("name"))
        with pytest.raises(DuplicateError):
            tc.add_transformations(Transformation("name", namespace=None, version=None))

    def test_add_invalid_transformation(self):
        tc = TransformationCatalog()
        with pytest.raises(TypeError) as e:
            tc.add_transformations(1)

        assert "invalid transformation: 1" in str(e)

    def test_add_container(self):
        tc = TransformationCatalog()
        tc.add_containers(Container("container", Container.DOCKER, "image", ["mount"]))

        assert len(tc.containers) == 1
        assert "container" in tc.containers

    def test_add_duplicate_container(self):
        tc = TransformationCatalog()
        tc.add_containers(Container("container", Container.DOCKER, "image", ["mount"]))
        with pytest.raises(DuplicateError):
            tc.add_containers(
                Container("container", Container.DOCKER, "image", ["mount"])
            )

    def test_add_invalid_container(self):
        tc = TransformationCatalog()
        with pytest.raises(TypeError) as e:
            tc.add_containers("container")

        assert "invalid container: container" in str(e)

    def test_chaining(self):
        tc = TransformationCatalog()

        (
            tc.add_transformations(Transformation("t1"))
            .add_transformations(Transformation("t2"))
            .add_containers(
                Container("container1", Container.DOCKER, "image", ["mount1", "mount2"])
            )
            .add_containers(
                Container("container2", Container.DOCKER, "image", ["mount1", "mount2"])
            )
        )

        assert "None::t1::None" in tc.transformations
        assert "None::t2::None" in tc.transformations
        assert "container1" in tc.containers
        assert "container2" in tc.containers

    def test_tojson(self, convert_yaml_schemas_to_json, load_schema):
        tc = TransformationCatalog()
        (
            tc.add_transformations(
                Transformation("t1").add_sites(
                    TransformationSite("local", "/pfn", False)
                )
            )
            .add_transformations(
                Transformation("t2").add_sites(
                    TransformationSite("local", "/pfn", False)
                )
            )
            .add_containers(
                Container("container1", Container.DOCKER, "image", ["mount1"])
            )
            .add_containers(
                Container("container2", Container.DOCKER, "image", ["mount1"])
            )
        )

        expected = {
            "pegasus": PEGASUS_VERSION,
            "transformations": [
                {
                    "name": "t1",
                    "sites": [{"name": "local", "pfn": "/pfn", "type": "installed"}],
                },
                {
                    "name": "t2",
                    "sites": [{"name": "local", "pfn": "/pfn", "type": "installed"}],
                },
            ],
            "containers": [
                {
                    "name": "container1",
                    "type": "docker",
                    "image": "image",
                    "mounts": ["mount1"],
                },
                {
                    "name": "container2",
                    "type": "docker",
                    "image": "image",
                    "mounts": ["mount1"],
                },
            ],
        }

        expected["transformations"] = sorted(
            expected["transformations"], key=lambda t: t["name"]
        )
        expected["containers"] = sorted(expected["containers"], key=lambda c: c["name"])

        result = json.loads(json.dumps(tc, cls=_CustomEncoder))

        result["transformations"] = sorted(
            result["transformations"], key=lambda t: t["name"]
        )
        result["containers"] = sorted(result["containers"], key=lambda c: c["name"])

        tc_schema = load_schema("tc-5.0.json")
        validate(instance=result, schema=tc_schema)

        assert result == expected

    def test_tojson_no_containers(self, convert_yaml_schemas_to_json, load_schema):
        tc = TransformationCatalog()
        (
            tc.add_transformations(
                Transformation("t1").add_sites(
                    TransformationSite("local", "/pfn", False)
                )
            ).add_transformations(
                Transformation("t2").add_sites(
                    TransformationSite("local2", "/pfn", True)
                )
            )
        )

        expected = {
            "pegasus": PEGASUS_VERSION,
            "transformations": [
                {
                    "name": "t1",
                    "sites": [{"name": "local", "pfn": "/pfn", "type": "installed"}],
                },
                {
                    "name": "t2",
                    "sites": [{"name": "local2", "pfn": "/pfn", "type": "stageable"}],
                },
            ],
        }

        expected["transformations"] = sorted(
            expected["transformations"], key=lambda t: t["name"]
        )

        result = json.loads(json.dumps(tc, cls=_CustomEncoder))

        result["transformations"] = sorted(
            result["transformations"], key=lambda t: t["name"]
        )

        tc_schema = load_schema("tc-5.0.json")
        validate(instance=result, schema=tc_schema)

        assert expected == result

    def test_write(self):
        tc = TransformationCatalog()
        (
            tc.add_transformations(Transformation("t1")).add_transformations(
                Transformation("t2")
            )
        )

        expected = {
            "pegasus": "5.0",
            "transformations": [
                {"name": "t1", "sites": []},
                {"name": "t2", "sites": []},
            ],
        }

        expected["transformations"] = sorted(
            expected["transformations"], key=lambda t: t["name"]
        )

        with NamedTemporaryFile("r+") as f:
            tc.write(f, _format="json")
            f.seek(0)
            result = json.load(f)

        result["transformations"] = sorted(
            expected["transformations"], key=lambda t: t["name"]
        )

        assert result == expected

    @pytest.mark.parametrize(
        "_format, loader", [("json", json.load), ("yml", yaml.safe_load)]
    )
    def test_example_transformation_catalog(
        self, convert_yaml_schemas_to_json, load_schema, _format, loader
    ):
        # validates the sample tc in pegasus/etc/sample-5.0-data/tc.yml
        tc = TransformationCatalog()

        foo = (
            Transformation("foo")
            .add_profile_globus(max_time=2)
            .add_profile_dagman(retry=2)
            .add_metadata(size=2048)
            .add_sites(
                TransformationSite(
                    "local",
                    "/nfs/u2/ryan/bin/foo",
                    True,
                    arch=Arch.X86_64,
                    os_type=OS.LINUX,
                )
                .add_env(JAVA_HOME="/usr/bin/java")
                .add_metadata(size=2048)
            )
            .add_requirement("bar")
            .add_shell_hook(EventType.START, "/bin/echo 'starting'")
        )

        bar = Transformation("bar").add_sites(
            TransformationSite(
                "local",
                "/nfs/u2/ryan/bin/bar",
                True,
                arch=Arch.X86_64,
                os_type=OS.LINUX,
            )
        )

        centos_pegasus_container = Container(
            "centos-pegasus",
            Container.DOCKER,
            "docker:///ryan/centos-pegasus:latest",
            ["/Volumes/Work/lfs1:/shared-data/:ro"],
        ).add_env(JAVA_HOME="/usr/bin/java")

        (tc.add_transformations(foo, bar).add_containers(centos_pegasus_container))

        with NamedTemporaryFile(mode="r+") as f:
            tc.write(f, _format=_format)
            f.seek(0)
            tc_json = loader(f)

        tc_schema = load_schema("tc-5.0.json")
        validate(instance=tc_json, schema=tc_schema)

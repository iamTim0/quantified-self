"""Generate Python gRPC and Protobuf stubs from packages/proto/quantified_self/v1/*.proto."""

import os
import sys
from pathlib import Path
from grpc_tools import protoc

def generate():
    root_dir = Path(__file__).resolve().parent.parent.parent
    proto_dir = root_dir / "packages" / "proto"
    out_dir = root_dir / "packages" / "proto" / "gen" / "python"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Find include directory for google.protobuf imports inside grpc_tools
    import grpc_tools
    grpc_tools_dir = Path(grpc_tools.__file__).parent
    well_known_protos_dir = grpc_tools_dir / "_proto"

    proto_files = list((proto_dir / "quantified_self" / "v1").glob("*.proto"))
    
    args = [
        "protoc",
        f"-I{proto_dir}",
        f"-I{well_known_protos_dir}",
        f"--python_out={out_dir}",
        f"--grpc_python_out={out_dir}",
        *[str(f) for f in proto_files],
    ]

    print(f"Generating proto code for {len(proto_files)} files into {out_dir}...")
    res = protoc.main(args)
    if res != 0:
        print(f"Error generating proto files: {res}")
        sys.exit(res)
    
    # Create __init__.py files in output tree
    for d, _, _ in os.walk(out_dir):
        init_file = Path(d) / "__init__.py"
        if not init_file.exists():
            init_file.touch()

    print("Proto code generation complete.")

if __name__ == "__main__":
    generate()

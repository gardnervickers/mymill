{
  description = "Static linting and simulator scaffolding for the mymill LinuxCNC config";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
  };

  outputs =
    { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      systems = [
        "aarch64-darwin"
        "x86_64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = lib.genAttrs systems;
      pkgsFor = system: import nixpkgs { inherit system; };
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.python3
            ];
          };
        }
      );

      packages = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          hal-lint = pkgs.writeShellApplication {
            name = "hal-lint";
            runtimeInputs = [ pkgs.python3 ];
            text = ''
              exec ${pkgs.python3}/bin/python ${./scripts/hal_lint.py} "$@"
            '';
          };
          mymill-lima-sim = pkgs.writeShellApplication {
            name = "mymill-lima-sim";
            text = ''
              export MYMILL_REPO_ROOT="$PWD"
              exec ${pkgs.bash}/bin/bash ${./scripts/lima_mymill_sim.sh} "$@"
            '';
          };
        }
      );

      apps = forAllSystems (system: {
        hal-lint = {
          type = "app";
          program = "${self.packages.${system}.hal-lint}/bin/hal-lint";
        };
        mymill-lima-sim = {
          type = "app";
          program = "${self.packages.${system}.mymill-lima-sim}/bin/mymill-lima-sim";
        };
        default = self.apps.${system}.hal-lint;
      });
    };
}

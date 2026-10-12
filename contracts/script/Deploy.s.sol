// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {MeterCommitmentRegistry} from "../src/MeterCommitmentRegistry.sol";

/// Deploys the registry and grants AGGREGATOR_ROLE to the aggregator account.
/// Reads ADMIN_PRIVATE_KEY and AGGREGATOR_ADDRESS from the environment
/// (the Makefile exports .env). Run with: make deploy
contract Deploy is Script {
    function run() external returns (MeterCommitmentRegistry registry) {
        uint256 adminKey = vm.envUint("ADMIN_PRIVATE_KEY");
        address aggregator = vm.envAddress("AGGREGATOR_ADDRESS");

        vm.startBroadcast(adminKey);
        registry = new MeterCommitmentRegistry(vm.addr(adminKey));
        registry.grantRole(registry.AGGREGATOR_ROLE(), aggregator);
        vm.stopBroadcast();

        console.log("MeterCommitmentRegistry deployed at:", address(registry));
        console.log("Copy this address into CONTRACT_ADDRESS in .env");
    }
}

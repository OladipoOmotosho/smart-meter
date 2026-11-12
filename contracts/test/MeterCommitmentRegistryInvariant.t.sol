// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MeterCommitmentRegistry} from "../src/MeterCommitmentRegistry.sol";

/// Models accepted operations from inputs and prior model state.
contract RegistryHandler is Test {
    struct FirstCommit {
        bool exists;
        bytes32 digest;
        address writer;
        uint256 timestamp;
    }

    uint256 public constant KEY_COUNT = 4;
    MeterCommitmentRegistry public immutable registry;
    bytes32 private immutable writerRole;
    address[3] public actors;
    bool[3] public writers;
    mapping(bytes32 => FirstCommit) public firstCommits;
    uint256 public calls;

    constructor(MeterCommitmentRegistry registry_, address admin, address writerA, address writerB) {
        registry = registry_;
        writerRole = registry_.AGGREGATOR_ROLE();
        actors = [admin, writerA, writerB];
    }

    function setWriter(uint8 callerSeed, uint8 targetSeed, bool grant) external {
        uint256 caller = uint256(callerSeed) % actors.length;
        uint256 target = uint256(targetSeed) % actors.length;
        bytes memory callData = grant
            ? abi.encodeCall(registry.grantRole, (writerRole, actors[target]))
            : abi.encodeCall(registry.revokeRole, (writerRole, actors[target]));
        bool allowed = caller == 0;
        vm.prank(actors[caller]);
        (bool success,) = address(registry).call(callData);
        assertEq(success, allowed, "role change disagrees with admin model");
        if (allowed) writers[target] = grant;
        ++calls;
    }

    function submit(uint8 callerSeed, uint8 keySeed, bytes32 digest, bool zeroDigest) external {
        uint256 caller = uint256(callerSeed) % actors.length;
        bytes32 key = bytes32(uint256(keySeed) % KEY_COUNT);
        if (zeroDigest) digest = bytes32(0);

        // Vary the timestamp so an overwrite of otherwise identical data is visible.
        uint256 timestamp = vm.getBlockTimestamp() + 1;
        vm.warp(timestamp);
        bool allowed = writers[caller] && digest != bytes32(0) && !firstCommits[key].exists;
        vm.prank(actors[caller]);
        (bool success,) = address(registry).call(abi.encodeCall(registry.commit, (key, digest)));
        assertEq(success, allowed, "commit disagrees with writer and first-commit model");
        if (allowed) firstCommits[key] = FirstCommit(true, digest, actors[caller], timestamp);
        ++calls;
    }
}

contract MeterCommitmentRegistryInvariantTest is Test {
    MeterCommitmentRegistry private registry;
    RegistryHandler private handler;

    function setUp() public {
        address admin = makeAddr("registry admin");
        registry = new MeterCommitmentRegistry(admin);
        handler = new RegistryHandler(registry, admin, makeAddr("writer A"), makeAddr("writer B"));

        bytes4[] memory selectors = new bytes4[](2);
        selectors[0] = RegistryHandler.setWriter.selector;
        selectors[1] = RegistryHandler.submit.selector;
        targetContract(address(handler));
        targetSelector(FuzzSelector({addr: address(handler), selectors: selectors}));
    }

    function invariant_RegistryMatchesFirstCommitAndRoleModel() public view {
        bytes32 role = registry.AGGREGATOR_ROLE();
        for (uint256 i; i < 3; ++i) {
            assertEq(registry.hasRole(role, handler.actors(i)), handler.writers(i));
        }
        for (uint256 i; i < handler.KEY_COUNT(); ++i) {
            bytes32 key = bytes32(i);
            (bool exists, bytes32 digest, address writer, uint256 timestamp) = handler.firstCommits(key);
            MeterCommitmentRegistry.Commitment memory actual = registry.getCommitment(key);
            assertEq(registry.isCommitted(key), exists);
            assertEq(actual.digest, digest);
            assertEq(actual.submitter, writer);
            assertEq(actual.committedAt, timestamp);
        }
    }

    function afterInvariant() public view {
        assertGt(handler.calls(), 0, "no modeled operations ran");
    }
}

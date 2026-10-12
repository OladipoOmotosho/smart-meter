// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {MeterCommitmentRegistry} from "../src/MeterCommitmentRegistry.sol";

/// Contract tests. Each test is skipped until you write it (Step 3).
/// Delete the vm.skip(true) line in a test once you fill it in.
contract MeterCommitmentRegistryTest is Test {
    MeterCommitmentRegistry internal registry;

    address internal admin = makeAddr("admin");
    address internal aggregator = makeAddr("aggregator");
    address internal attacker = makeAddr("attacker");

    bytes32 internal constant KEY = keccak256("M1|2012-04-01T00:00:00Z");
    bytes32 internal constant DIGEST = keccak256("example digest");

    function setUp() public {
        registry = new MeterCommitmentRegistry(admin);
        bytes32 role = registry.AGGREGATOR_ROLE();
        vm.prank(admin);
        registry.grantRole(role, aggregator);
    }

    /// The aggregator commits; isCommitted becomes true.
    function test_AggregatorCanCommit() public {
        vm.skip(true);
        // TODO: prank as aggregator, commit KEY/DIGEST, assert isCommitted(KEY)
    }

    /// getCommitment returns the digest, the block timestamp and the submitter.
    function test_GetCommitmentReturnsStoredValues() public {
        vm.skip(true);
        // TODO: vm.warp to a known time, commit, then check all three fields
    }

    /// An unknown key returns an all-zero commitment and isCommitted is false.
    function test_UnknownKeyIsEmpty() public {
        vm.skip(true);
        // TODO
    }

    /// Attack A2: an account without AGGREGATOR_ROLE is rejected.
    function test_RevertWhen_UnauthorizedCommit() public {
        vm.skip(true);
        // TODO: expect IAccessControl.AccessControlUnauthorizedAccount(attacker, role)
    }

    /// Attack A3: committing the same key twice is rejected, even by the aggregator.
    function test_RevertWhen_KeyAlreadyCommitted() public {
        vm.skip(true);
        // TODO: expect MeterCommitmentRegistry.AlreadyCommitted(KEY)
    }

    /// A zero digest is rejected.
    function test_RevertWhen_ZeroDigest() public {
        vm.skip(true);
        // TODO
    }

    /// A successful commit emits Committed with the right arguments.
    function test_EmitsCommittedEvent() public {
        vm.skip(true);
        // TODO: vm.expectEmit, then emit the expected event, then commit
    }

    // Keeps the IAccessControl import used until you write the unauthorized test.
    function _accessControlSelector() internal pure returns (bytes4) {
        return IAccessControl.AccessControlUnauthorizedAccount.selector;
    }
}

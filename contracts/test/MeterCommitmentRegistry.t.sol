// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {MeterCommitmentRegistry} from "../src/MeterCommitmentRegistry.sol";

/// Behavioral checks for the append-once, role-controlled registry.
contract MeterCommitmentRegistryTest is Test {
    MeterCommitmentRegistry internal registry;

    address internal admin = makeAddr("admin");
    address internal aggregator = makeAddr("aggregator");
    address internal attacker = makeAddr("attacker");

    bytes32 internal constant KEY = keccak256("M1|2012-04-01T00:00:00Z");
    bytes32 internal constant DIGEST = keccak256("example digest");
    event Committed(bytes32 indexed recordKey, bytes32 digest, address indexed submitter, uint64 committedAt);

    function setUp() public {
        registry = new MeterCommitmentRegistry(admin);
        bytes32 role = registry.AGGREGATOR_ROLE();
        vm.prank(admin);
        registry.grantRole(role, aggregator);
    }

    /// The aggregator commits; isCommitted becomes true.
    function test_AggregatorCanCommit() public {
        vm.prank(aggregator);
        registry.commit(KEY, DIGEST);
        assertTrue(registry.isCommitted(KEY));
    }

    /// getCommitment returns the digest, the block timestamp and the submitter.
    function test_GetCommitmentReturnsStoredValues() public {
        vm.warp(1234);
        vm.prank(aggregator);
        registry.commit(KEY, DIGEST);
        MeterCommitmentRegistry.Commitment memory entry = registry.getCommitment(KEY);
        assertEq(entry.digest, DIGEST);
        assertEq(entry.committedAt, 1234);
        assertEq(entry.submitter, aggregator);
    }

    /// An unknown key returns an all-zero commitment and isCommitted is false.
    function test_UnknownKeyIsEmpty() public {
        MeterCommitmentRegistry.Commitment memory entry = registry.getCommitment(KEY);
        assertEq(entry.digest, bytes32(0));
        assertEq(entry.committedAt, 0);
        assertEq(entry.submitter, address(0));
        assertFalse(registry.isCommitted(KEY));
    }

    /// Attack A2: an account without AGGREGATOR_ROLE is rejected.
    function test_RevertWhen_UnauthorizedCommit() public {
        vm.startPrank(attacker);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, attacker, registry.AGGREGATOR_ROLE()
            )
        );
        registry.commit(KEY, DIGEST);
        vm.stopPrank();
        assertFalse(registry.isCommitted(KEY));
    }

    /// Attack A3: committing the same key twice is rejected, even by the aggregator.
    function test_RevertWhen_KeyAlreadyCommitted() public {
        vm.prank(aggregator);
        registry.commit(KEY, DIGEST);
        MeterCommitmentRegistry.Commitment memory original = registry.getCommitment(KEY);
        vm.prank(aggregator);
        vm.expectRevert(abi.encodeWithSelector(MeterCommitmentRegistry.AlreadyCommitted.selector, KEY));
        registry.commit(KEY, keccak256("replacement"));
        MeterCommitmentRegistry.Commitment memory afterAttempt = registry.getCommitment(KEY);
        assertEq(afterAttempt.digest, original.digest);
        assertEq(afterAttempt.committedAt, original.committedAt);
        assertEq(afterAttempt.submitter, original.submitter);
    }

    /// A zero digest is rejected.
    function test_RevertWhen_ZeroDigest() public {
        vm.prank(aggregator);
        vm.expectRevert(MeterCommitmentRegistry.ZeroDigest.selector);
        registry.commit(KEY, bytes32(0));
        assertFalse(registry.isCommitted(KEY));
    }

    /// A successful commit emits Committed with the right arguments.
    function test_EmitsCommittedEvent() public {
        vm.warp(1234);
        vm.expectEmit(true, false, true, true, address(registry));
        emit Committed(KEY, DIGEST, aggregator, 1234);
        vm.prank(aggregator);
        registry.commit(KEY, DIGEST);
    }

    function test_AdminHasNoImplicitWriterRole() public {
        vm.startPrank(admin);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, admin, registry.AGGREGATOR_ROLE()
            )
        );
        registry.commit(KEY, DIGEST);
        vm.stopPrank();
    }

    function test_RevocationBlocksFutureWritesButPreservesPast() public {
        vm.prank(aggregator);
        registry.commit(KEY, DIGEST);
        bytes32 role = registry.AGGREGATOR_ROLE();
        vm.prank(admin);
        registry.revokeRole(role, aggregator);
        vm.startPrank(aggregator);
        vm.expectRevert(
            abi.encodeWithSelector(
                IAccessControl.AccessControlUnauthorizedAccount.selector, aggregator, registry.AGGREGATOR_ROLE()
            )
        );
        registry.commit(keccak256("later"), DIGEST);
        vm.stopPrank();
        assertEq(registry.getCommitment(KEY).digest, DIGEST);
    }

    function test_ZeroAdminRejected() public {
        vm.expectRevert(MeterCommitmentRegistry.InvalidAdmin.selector);
        new MeterCommitmentRegistry(address(0));
    }

    function testFuzz_FirstCommitRemainsFixed(bytes32 key, bytes32 first, bytes32 replacement) public {
        vm.assume(first != bytes32(0));
        vm.prank(aggregator);
        registry.commit(key, first);
        MeterCommitmentRegistry.Commitment memory original = registry.getCommitment(key);
        vm.prank(aggregator);
        vm.expectRevert(abi.encodeWithSelector(MeterCommitmentRegistry.AlreadyCommitted.selector, key));
        registry.commit(key, replacement == bytes32(0) ? first : replacement);
        MeterCommitmentRegistry.Commitment memory afterAttempt = registry.getCommitment(key);
        assertEq(afterAttempt.digest, original.digest);
        assertEq(afterAttempt.submitter, original.submitter);
        assertEq(afterAttempt.committedAt, original.committedAt);
    }
}

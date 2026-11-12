// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {Vm} from "forge-std/Vm.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {IERC165} from "@openzeppelin/contracts/utils/introspection/IERC165.sol";
import {SafeCast} from "@openzeppelin/contracts/utils/math/SafeCast.sol";
import {MeterCommitmentRegistry} from "../src/MeterCommitmentRegistry.sol";

/// Behavioral checks for the append-once, role-controlled registry.
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
    function test_UnknownKeyIsEmpty() public view {
        _assertEmpty(KEY);
    }

    function _assertEmpty(bytes32 key) internal view {
        MeterCommitmentRegistry.Commitment memory entry = registry.getCommitment(key);
        assertEq(entry.digest, bytes32(0));
        assertEq(entry.committedAt, 0);
        assertEq(entry.submitter, address(0));
        assertFalse(registry.isCommitted(key));
    }

    /// Attack A2: an account without AGGREGATOR_ROLE is rejected.
    function test_RevertWhen_UnauthorizedCommit() public {
        bytes32 role = registry.AGGREGATOR_ROLE();
        vm.recordLogs();
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, attacker, role)
        );
        vm.prank(attacker);
        registry.commit(KEY, DIGEST);
        assertEq(vm.getRecordedLogs().length, 0);
        _assertEmpty(KEY);
    }

    /// Attack A3: committing the same key twice is rejected, even by the aggregator.
    function test_RevertWhen_KeyAlreadyCommitted() public {
        vm.prank(aggregator);
        registry.commit(KEY, DIGEST);
        MeterCommitmentRegistry.Commitment memory original = registry.getCommitment(KEY);
        vm.recordLogs();
        vm.expectRevert(abi.encodeWithSelector(MeterCommitmentRegistry.AlreadyCommitted.selector, KEY));
        vm.prank(aggregator);
        registry.commit(KEY, keccak256("replacement"));
        assertEq(vm.getRecordedLogs().length, 0);
        assertTrue(registry.isCommitted(KEY));
        MeterCommitmentRegistry.Commitment memory afterAttempt = registry.getCommitment(KEY);
        assertEq(afterAttempt.digest, original.digest);
        assertEq(afterAttempt.committedAt, original.committedAt);
        assertEq(afterAttempt.submitter, original.submitter);
    }

    /// A zero digest is rejected.
    function test_RevertWhen_ZeroDigest() public {
        vm.recordLogs();
        vm.expectRevert(MeterCommitmentRegistry.ZeroDigest.selector);
        vm.prank(aggregator);
        registry.commit(KEY, bytes32(0));
        assertEq(vm.getRecordedLogs().length, 0);
        _assertEmpty(KEY);
    }

    /// A successful commit emits Committed with the right arguments.
    function test_EmitsCommittedEvent() public {
        vm.warp(1234);
        vm.recordLogs();
        vm.prank(aggregator);
        registry.commit(KEY, DIGEST);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        assertEq(logs.length, 1);
        assertEq(logs[0].emitter, address(registry));
        assertEq(logs[0].topics.length, 3);
        assertEq(logs[0].topics[0], keccak256("Committed(bytes32,bytes32,address,uint64)"));
        assertEq(logs[0].topics[1], KEY);
        assertEq(logs[0].topics[2], bytes32(uint256(uint160(aggregator))));
        assertEq(logs[0].data, abi.encode(DIGEST, uint64(1234)));
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

    function test_WriterCannotGrantOrRevokeWriterRole() public {
        bytes32 role = registry.AGGREGATOR_ROLE();
        bytes memory denied = abi.encodeWithSelector(
            IAccessControl.AccessControlUnauthorizedAccount.selector, aggregator, registry.DEFAULT_ADMIN_ROLE()
        );
        vm.expectRevert(denied);
        vm.prank(aggregator);
        registry.grantRole(role, attacker);
        vm.expectRevert(denied);
        vm.prank(aggregator);
        registry.revokeRole(role, aggregator);
        assertFalse(registry.hasRole(role, attacker));
        assertTrue(registry.hasRole(role, aggregator));
    }

    function test_ZeroKeyIsValid() public {
        _assertEmpty(bytes32(0));
        vm.prank(aggregator);
        registry.commit(bytes32(0), DIGEST);
        assertTrue(registry.isCommitted(bytes32(0)));
        assertEq(registry.getCommitment(bytes32(0)).digest, DIGEST);
        _assertEmpty(KEY);
    }

    function test_SecondWriterCannotReuseKeyWithEitherDigest() public {
        bytes32 role = registry.AGGREGATOR_ROLE();
        vm.prank(admin);
        registry.grantRole(role, attacker);
        vm.warp(1234);
        vm.prank(aggregator);
        registry.commit(KEY, DIGEST);
        vm.warp(5678);

        bytes memory duplicate = abi.encodeWithSelector(MeterCommitmentRegistry.AlreadyCommitted.selector, KEY);
        vm.expectRevert(duplicate);
        vm.prank(attacker);
        registry.commit(KEY, DIGEST);
        vm.expectRevert(duplicate);
        vm.prank(attacker);
        registry.commit(KEY, keccak256("replacement"));

        MeterCommitmentRegistry.Commitment memory entry = registry.getCommitment(KEY);
        assertEq(entry.digest, DIGEST);
        assertEq(entry.submitter, aggregator);
        assertEq(entry.committedAt, 1234);
    }

    /// The administrator role governs the writer role and itself; nothing else changes that.
    function test_DefaultAdminAdministersWriterRole() public view {
        bytes32 adminRole = registry.DEFAULT_ADMIN_ROLE();
        assertEq(registry.getRoleAdmin(registry.AGGREGATOR_ROLE()), adminRole);
        assertEq(registry.getRoleAdmin(adminRole), adminRole);
        assertTrue(registry.hasRole(adminRole, admin));
        assertFalse(registry.hasRole(adminRole, aggregator));
    }

    function test_SupportsOnlyDeclaredInterfaces() public view {
        assertTrue(registry.supportsInterface(type(IAccessControl).interfaceId));
        assertTrue(registry.supportsInterface(type(IERC165).interfaceId));
        assertFalse(registry.supportsInterface(0xffffffff));
    }

    /// renounceRole is inherited public API: only the holder may drop its own role.
    function test_RenounceRoleOnlyByHolderAndBlocksFutureWrites() public {
        bytes32 role = registry.AGGREGATOR_ROLE();
        vm.prank(aggregator);
        registry.commit(KEY, DIGEST);

        vm.expectRevert(IAccessControl.AccessControlBadConfirmation.selector);
        vm.prank(attacker);
        registry.renounceRole(role, aggregator);
        assertTrue(registry.hasRole(role, aggregator));

        vm.prank(aggregator);
        registry.renounceRole(role, aggregator);
        assertFalse(registry.hasRole(role, aggregator));
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, aggregator, role)
        );
        vm.prank(aggregator);
        registry.commit(keccak256("later"), DIGEST);
        assertEq(registry.getCommitment(KEY).digest, DIGEST);
        assertEq(registry.getCommitment(KEY).submitter, aggregator);
    }

    /// An administrator that renounces leaves the writer set frozen; existing writers keep working.
    function test_AdminRenounceFreezesWriterSet() public {
        bytes32 adminRole = registry.DEFAULT_ADMIN_ROLE();
        bytes32 role = registry.AGGREGATOR_ROLE();
        vm.startPrank(admin);
        registry.renounceRole(adminRole, admin);
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, admin, adminRole)
        );
        registry.grantRole(role, attacker);
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, admin, adminRole)
        );
        registry.revokeRole(role, aggregator);
        vm.stopPrank();
        assertFalse(registry.hasRole(role, attacker));
        vm.prank(aggregator);
        registry.commit(KEY, DIGEST);
        assertTrue(registry.isCommitted(KEY));
    }

    /// The timestamp downcast guard rejects without storage or events.
    function test_RevertWhen_TimestampExceedsUint64() public {
        uint256 tooLate = uint256(type(uint64).max) + 1;
        vm.warp(tooLate);
        vm.recordLogs();
        vm.expectRevert(abi.encodeWithSelector(SafeCast.SafeCastOverflowedUintDowncast.selector, uint8(64), tooLate));
        vm.prank(aggregator);
        registry.commit(KEY, DIGEST);
        assertEq(vm.getRecordedLogs().length, 0);
        _assertEmpty(KEY);
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
